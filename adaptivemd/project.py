##############################################################################
# adaptiveMD: A Python Framework to Run Adaptive Molecular Dynamics (MD)
#             Simulations on HPC Resources
# Copyright 2017 FU Berlin and the Authors
#
# Authors: Jan-Hendrik Prinz
#          John Ossyra
# Contributors:
#
# `adaptiveMD` is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation, either version 2.1
# of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with MDTraj. If not, see <http://www.gnu.org/licenses/>.
##############################################################################
#from __future__ import absolute_import, print_function


import threading
import time
import numpy as np
import os
import types

from .file import URLGenerator, File
from .engine import Trajectory
from .bundle import StoredBundle
from .condition import Condition
from .resource import Resource
from .generator import TaskGenerator
from .model import Model
from .task import Task
from .worker import Worker
from .logentry import LogEntry
from .plan import ExecutionPlan

# TODO exec manager with multiprocessing
# TODO attach main instances rp to project
#from .rp import client

from .configuration import Configuration
from .util import get_logger


from .mongodb import MongoDBStorage, ObjectStore, FileStore, DataDict, WeakValueCache


logger = get_logger(__name__)


class Project(object):
    """
    A simulation project

    Notes
    -----

    You will later create `Scheduler` objects that explicitly correspond to
    a specific cue on a specific cluster that is accessible from within this
    shared FS resource.

    Attributes
    ----------

    name : str
        a short descriptive name for the project. This name will be used in the
        database creation also.
    resource : `Resource`
        a resource to run the project on. 
    files : :class:`Bundle`
        a set of file objects that are available in the project and are
        believed to be available within the resource as long as the project
        lives
    trajectories : `ViewBundle`
        all `File` object that are of `Trajectory` type and which have a
        positive `created` attribute. This means the file was really created
        and has not been altered yet.
    workers : `Bundle`
        a set of all registered `Worker` instanced in the project
    files : `Bundle`
        a set of file objects that are available in the project and are
        believed to be available within the resource as long as the project
        lives
    models : `Bundle`
        a set of stored models in the DB
    configurations : `Bundle`
        a set of resource configurations availabe for executing tasks using the
        Radical Pilot execution manager
    tasks : `Bundle`
        a set of all queued `Task`s in the project
    logs : `Bundle`
        a set of all stored log entries
    data : `Bundle`
        a set of `DataDict` objects that represent completely stored files in
        the database of arbitrary size
    storage : `MongoDBStorage`
        the mongodb storage wrapper to access the database of the project
    _worker_dead_time : int
        the time after which an unresponsive worker is considered dead. Its
        tasks will be assigned the state set in
        :attr:`_set_task_state_from_dead_workers`.
        Default is 60s. Make sure that
        the heartbeat of a worker is much less that this.
    _set_task_state_from_dead_workers : str
        if a worker is dead then its tasks are assigned this state. Default is
        ``created`` which means the task will be restarted by another worker.
        You can also chose ``halt`` or ``cancelled``. See `Task` for details

    See also
    --------
    `Task`

    """

    _db_url = os.environ.get("ADMD_DBURL")

    if _db_url:
        MongoDBStorage._db_url = _db_url

    @classmethod
    def set_dburl(cls, dburl):
        MongoDBStorage._db_url = dburl

    @classmethod
    def set_dblocation(cls, hostname, portnumber=None):
        '''
        Use this method to set the full address of the MongoDB
        used by the project.
        '''
        if portnumber:
            cls.set_dbhost(hostname)
            cls.set_dbport(portnumber)
        else:
            MongoDBStorage.set_location(hostname)

    @classmethod
    def set_dbport(cls, portnumber):
        '''
        Set the port number used by the MongoDB host
        '''
        MongoDBStorage.set_port(portnumber)

    @classmethod
    def set_dbhost(cls, hostname):
        '''
        Set the hostname of MongoDB used by the project
        '''
        MongoDBStorage.set_host(hostname)

    def set_current_configuration(self, configuration=None):
        '''
        Set the configuration to use by default

        If argument is `None`, will try to get best option
        from previously stored configurations starting with
        check for one marked for use. Can give name of
        stored configuration object, resource_name it uses,
        or a `Configuration` instance for manual changes.

        Parameters
        ----------
        configuration : `None`, `str` or `Configuration`
        '''

        cfg = None

        # need cfg<Bundle> --> cfg<list>
        # or   cfg<Object> --> cfg<list>
        # to do some indexing below

        # ORDER matters in conditions here!
        if isinstance(configuration, Configuration):
            cfg = [ configuration ]

        elif isinstance(configuration, str):
            cfg = list(self.configurations.a('name', configuration))

        elif len(self.configurations) == 1:
            cfg = [ self.configurations.one ]

        elif configuration is None:
            cfg = list(self.configurations.m('current', True))

            if len(cfg) == 0:
                cfg = list(self.configurations.a('name', 'local.localhost'))

        # TODO always exactly 1 airtight?
        #      also - no rule for when reading from file and multiple
        #             configs try to set current to True
        #             - last one wins?
        # cfg had better be a list
        if cfg:
            if len(cfg) == 1:
                [setattr(c, 'current', False) for c in self.configurations]

                cur = cfg[0]
                cur.current = True
                self._current_configuration = cur

            else:
                logger.error("Configuration selection must match a single item")

        else:
            logger.error("Did not set a new current configuration")
            logger.error("Setting current to Summit")
            self.configurations.a("name", "summit").one.current = True
            logger.error(["%s: %s" % (c.name, str(c.current)) for c in self.configurations])

    def read_configurations(self, configuration_file=None, default_configuration=None):
        '''
        Read in a configurations file to define supported resources.

        Multiple configurations can be stored, with one specified
        as a current default configuration. If no argument is given,
        this method will try to read a file with the project's
        name in the current working directory. Give configuration
        name or instance to set as default.

        See adaptivemd/examples/configurations.txt for an example
        of the format.

        Parameters
        ----------
        configuration_file : `str`
            Path to configuration file
        default_configuration : `str` or `Configuration`
            Name or instance of configuration to use by default
        '''

        configurations = Configuration.read_configurations(
            configuration_file, self.name)

        for c in configurations:
            if not self.configurations or c.name not in self.configurations.all.name:
                self.configurations.add(c) 

        self.set_current_configuration(default_configuration)

    def __init__(self, name):

        self.name = name

        # TODO reference to rp client here
        # TODO control callbacks/watchers
        #      here, delegate to rp if used
        #self.execution_manager = client()
        self.schedulers = set()

        self.models = StoredBundle()
        self.generators = StoredBundle()
        self.files = StoredBundle()
        self.tasks = StoredBundle()
        self.workers = StoredBundle()
        self.logs = StoredBundle()
        self.data = StoredBundle()
        self.configurations = StoredBundle()
        self.resources = StoredBundle()

        self._all_trajectories = self.files.c(Trajectory)
        self.trajectories = self._all_trajectories.v(lambda x: x.exists)

        self._events = []

        # generator for trajectory names
        self.traj_name = URLGenerator(
            os.path.join(
                'sandbox:///projects/',
                self.name,
                'trajs',
                '{count:08d}',
                ''))

        self.storage = None

        self._client = None
        self._open_db()

        self._lock = threading.Lock()
        self._event_timer = None
        self._stop_event = None

        # timeout if a worker is not changing its heartbeat in the last n seconds
        self._worker_dead_time = 60

        # tasks from dead workers that were started or queue should do what?
        self._set_task_state_from_dead_workers = 'created'

        # instead mark these as failed and decide manually
        # self._set_task_state_from_dead_workers = 'fail'

        # or do not care. This is fast but not recommended
        # self._set_task_state_from_dead_workers = None

        self._current_configuration = None
        if len(self.configurations) > 0:
            self.set_current_configuration()

    def initialize(self, configuration=None,
                   default_configuration=None):
        """
        Initialize a project

        This should only be called to setup the project and only the very
        first time. Later load different configurations with `read_configurations`
        and `set_configurations` methods.

        Parameters
        ----------


        """
        if len(self.storage.stores) == 0:
            self.storage.close()

            st = MongoDBStorage(self.name, 'w')
            # st.create_store(ObjectStore('objs', None))
            st.create_store(ObjectStore('generators', TaskGenerator))
            st.create_store(ObjectStore('files', File))
            st.create_store(ObjectStore('resources', Resource))
            st.create_store(ObjectStore('configurations', Configuration))
            st.create_store(ObjectStore('models', Model))
            st.create_store(ObjectStore('tasks', Task))
            st.create_store(ObjectStore('workers', Worker))
            st.create_store(ObjectStore('logs', LogEntry))
            st.create_store(FileStore('data', DataDict))

            st.close()

            self._open_db()

            # this method will save configurations to the storage
            # if a valid configuration file is found
            if isinstance(configuration, str):
                logger.debug("reading a configuration")
                self.read_configurations(
                    configuration, default_configuration)

            elif isinstance(configuration, dict):
                self.configurations.add(
                    Configuration('local', **configuration))

            elif not configuration:
                self.configurations.add(Configuration('local'))

            if not self._current_configuration:
                self.set_current_configuration(self.configurations.last)

        else:
            logger.warning("Not reinitializing project")

    def request_resource(self, submit_command, destination=""):
    #def request_resource(self, total_cpus, total_time,
    #                     total_gpus=0, destination=''):
        '''
        Request to use a resource for Radical Pilot.

        Instantiated Radical Pilot Clients can acquire the
        description of a requested resource and submit a
        Pilot Job on the Resource LRMS using the parameters.
        given to this method. A workflow targeted to this
        resource is then executed within this Pilot.

        Parameters
        ----------
        total_cpus : `int`
            Total cpus to request (n_nodes * cpu_per_node)
        total_time : `int`
            Total time to request in minutes
        total_gpu : `int`
            Total gpu to request
        destination : `str`
            Name of resource_configuration in Radical Pilot

        '''

        if destination == 'current':
            destination = self._current_configuration.resource["resource_name"]

        r = Resource(submit_command)
        #r = Resource(total_cpus, total_time,
        #             total_gpus, destination)

        self.resources.add(r)

    def _open_db(self):
        # open DB and load status
        self.storage = MongoDBStorage(self.name)

        if hasattr(self.storage, 'tasks'):
            self.files.set_store(self.storage.files)
            self.generators.set_store(self.storage.generators)
            self.configurations.set_store(self.storage.configurations)
            self.models.set_store(self.storage.models)
            self.tasks.set_store(self.storage.tasks)
            self.workers.set_store(self.storage.workers)
            self.logs.set_store(self.storage.logs)
            self.data.set_store(self.storage.data)
            self.resources.set_store(self.storage.resources)

            self.storage.files.set_caching(True)
            self.storage.models.set_caching(WeakValueCache())
            self.storage.generators.set_caching(True)
            self.storage.tasks.set_caching(True)
            self.storage.workers.set_caching(True)
            self.storage.resources.set_caching(True)
            self.storage.configurations.set_caching(True)
            self.storage.data.set_caching(WeakValueCache())
            self.storage.logs.set_caching(WeakValueCache())

            # make sure that the file number will be new
            # TODO This may note work...
            self.traj_name.initialize_from_files(self.trajectories)

    def reconnect(self):
        """
        Reconnect the DB

        """
        self._open_db()

    def _close_db(self):
        self.storage.close()

    @classmethod
    def list(cls):
        """
        List all projects in the DB

        Returns
        -------
        list of str
            a list of all project names

        """
        storages = MongoDBStorage.list_storages()
        return storages

    @classmethod
    def delete(cls, name):
        """
        Delete a complete project

        All project data will be deleted from the database.

        Notes
        -----
        Attention!!!! This cannot be undone!!!!

        Parameters
        ----------
        name : str
            the project name to be deleted

        """
        MongoDBStorage.delete_storage(name)

    def close(self):
        """
        Close the project and all related sessions and DB connections

        """
        self.stop()
        self._close_db()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        fail = True
        if exc_type is None:
            pass
        elif issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            # self.report.warn('exit requested\n')
            pass
        elif issubclass(exc_type, Exception):
            # self.report.error('caught exception: %s\n' % exc_type)
            fail = False

        self.close()

        return fail

    @property
    def configuration(self):
        return self._current_configuration

    def queue(self, task, *args, **kwargs):#tasks, resource_name=None):
        """
        Submit jobs to the worker queue

        Parameters
        ----------
        tasks : (list of) `Task` or `Trajectory`
            anything that can be run like a `Task` or a `Trajectory` with engine

        """

        # TODO do a direct association with resource
        #      to target multiple simultaneously:
        #      r.queue(tasks)
        #      p.queue(r, tasks)
        if 'resource_name' in kwargs:
            resource_name = kwargs['resource_name']

        else:
            resource_name = None

        if isinstance(resource_name, str):
            resource_name = [resource_name]

        elif resource_name is None:
            resource_name = [resource_name]

        assert isinstance(resource_name, list)

        _task = list()
        args  = list(args)

        if isinstance(task, Task):
            _task.append(task)

        elif isinstance(task, Trajectory):
            _task.append(task.run(resource_name))

        elif isinstance(task, (list, tuple)):
            args.extend(task)

        for ta in args:
            # DON'T need to check for analysis
            # since they must come as task
            if isinstance(ta, Trajectory):
                if ta.engine is not None:
                    _task.append(ta.run(resource_name))
            elif isinstance(ta, Task):
                    _task.append(ta)

        self.tasks.add(_task)

    def new_trajectory(self, frame, length, engine=None, number=1):
        """
        Convenience function to create a new `Trajectory` object

        It will use incrementing numbers to create trajectory names used in
        the engine executions. Use this function to always get an unused
        trajectory name.

        Parameters
        ----------
        frame : `File` or `Frame`
            if given a `File` it is assumed to be a ``.pdb`` file that contains
            initial coordinates. If a frame is given one assumes that this
            `Frame` is the initial structure / frame zero in this trajectory
        length : int
            the length of the trajectory
        engine : `Engine` or None
            the engine used to generate the trajectory. The engine contains all
            the specifics about the trajectory internal structure since it is the
            responsibility of the engine to really create the trajectory.
        number : int
            the number of trajectory objects to be returned. If ``1`` it will be
            a single object. Otherwise a list of `Trajectory` objects.

        Returns
        -------
        `Trajectory` or list of `Trajectory`

        """
        if number == 1:
            traj = Trajectory(next(self.traj_name), frame, length, engine)
            return [traj]

        elif number > 1:
            return [self.new_trajectory(frame, length, engine)[0] for _ in range(number)]

    def on_ntraj(self, numbers):
        """
        Return a condition that is true as soon a the project has n trajectories

        Parameters
        ----------
        numbers : int or iterator of int
            either a single int or an iterator that returns several ints

        Returns
        -------
        `NTrajectories` or generator of `NTrajectories`
            the single condition or a generator of conditions matching the ints
            in the iterator

        """
        if hasattr(numbers, '__iter__'):
            return (NTrajectories(self, n) for n in numbers)
        else:
            return NTrajectories(self, numbers)

    def on_nmodel(self, numbers):
        """
        Return a condition representing the reach of a certain number of models

        Parameters
        ----------
        numbers : int or iterator of int
            the number(s) of the models to be reached

        Returns
        -------
        (generator of) `Condition`
            a (list of) `Condition`
        """
        if hasattr(numbers, '__iter__'):
            return (NModels(self, n) for n in numbers)
        else:
            return NModels(self, numbers)

    # TODO: move to brain.sample_method
    def find_ml_next_frame(self, n_pick=10, randomly=False):
        """
        Find initial frames picked by inverse equilibrium distribution

        This is the simplest adaptive strategy possible. Start from the
        states more likely if a state has not been seen so much. Effectively
        stating that less knowledge of a state implies a higher likelihood to
        find a new state.

        Parameters
        ----------
        n_pick : int
             number of returned trajectories

        Returns
        -------
        list of `Frame`
            the list of trajectories with the selected initial points.
        """
        def get_model():
            if len(self.models) == 0:
                return None

            models = sorted(self.models, reverse=True,
                            key=lambda m: m.__time__)

            for model in models:
                assert(isinstance(model, Model))
                data = model.data
                c = data['msm']['C']
                s =  np.sum(c, axis=1)
                if 0 not in s:
                    q = 1.0 / s
                    return data, c, q

        model = get_model()

        if not randomly and model:

            data, c, q = model

            # not a good method to get n_states
            # populated clusters in
            # data['msm']['C'] may be less than k
            #n_states = data['clustering']['k']
            n_states = len(c)

            modeller = data['input']['modeller']

            outtype = modeller.outtype

            # the stride of the analyzed trajectories
            used_stride = modeller.engine.types[outtype].stride

            # all stride for full trajectories
            full_strides = modeller.engine.full_strides

            frame_state_list = {n: [] for n in range(n_states)}
            for nn, dt in enumerate(data['clustering']['dtrajs']):
                for mm, state in enumerate(dt):
                    # if there is a full traj with existing frame, use it
                    if any([(mm * used_stride) % stride == 0 for stride in full_strides]):
                        frame_state_list[state].append((nn, mm * used_stride))

            # remove states that do not have at least one frame
            for k in range(n_states):
                if len(frame_state_list[k]) == 0:
                    q[k] = 0.0

            # and normalize the remaining ones
            q /= np.sum(q)

            state_picks = np.random.choice(np.arange(len(q)), size=n_pick, p=q)

            logger.info("Using probability vector for states q:\n{}".format(q))
            logger.info("...we have chosen these states:\n {}".format([(s, q[s]) for s in state_picks]))

            filelist = data['input']['trajectories']

            picks = [
                frame_state_list[state][np.random.randint(0,
                len(frame_state_list[state]))]
                for state in state_picks
                ]

            trajlist = [filelist[pick[0]][pick[1]] for pick in picks]

        elif len(self.trajectories) > 0:
            # otherwise pick random
            logger.info("Using random vector to select new frames")
            # TODO simplify fast-method interface for ViewBundles
            #       to look like the (slow) pick methods
            current_trajs_index = [t.__uuid__ for t in self.trajectories]
            trajlist = [
                self.files._set.load(
                        current_trajs_index[
                        np.random.randint(len(current_trajs_index))]).pick()
                        for _ in range(n_pick)]

        else:
            trajlist = []

        logger.info("Trajectory picks list:\n{}".format(trajlist))
        return trajlist

    def new_ml_trajectory(self, engine, length, number=None, randomly=False):
        """
        Find trajectories that have initial points picked by inverse eq dist

        Parameters
        ----------
        engine : `Engine`
            the engine to be used
        length : int
            length of the trajectories returned
        number : int
            number of trajectories returned

        Returns
        -------
        list of `Trajectory`
            the list of `Trajectory` objects with initial frames chosen using
            :meth:`find_ml_next_frame`

        See Also
        --------
        :meth:`find_ml_next_frame`

        """
        # not checking case for len(length<list>) == number<int>
        # instead ignoring number/ assuming is number<None>
        if isinstance(length, int):
            assert(isinstance(number, int))
            length = [length]*number

        if isinstance(length, list):
            if number is None:
                number = len(length)

            trajectories = [self.new_trajectory(
                            frame, length[i], engine)
                            for i,frame in enumerate(
                            self.find_ml_next_frame(number, randomly))]

            return trajectories

    def events_done(self):
        """
        Check if all events are done

        Returns
        -------
        bool
            True if all events are done
        """
        return len(self._events) == 0

    def add_event(self, event):
        # FIXME see lower fixmes, this function doesn't ensure that
        #       the event argument is a compatible type
        """
        Attach an event to the project

        These events will not be stored and only run in the current python
        session. These are the parts responsible to create tasks given
        certain conditions.

        Parameters
        ----------
        event : `Event` or generator
            the event to be added or a generator function that is then
            converted to an `ExecutionPlan`

        Returns
        -------
        `Event`
            the actual event used

        """
        # FIXME this looks like it should map recursively
        #    return list(map(lambda e: self.add_event(e), event))
        if isinstance(event, (tuple, list)):
            return list(map(self._events.append, event))

        if isinstance(event, types.GeneratorType):
            event = ExecutionPlan(event)

        # FIXME what about any other arg type? should be rejected...

        self._events.append(event)

        logger.info('Events added. Remaining %d' % len(self._events))

        self.trigger()
        return event

    def trigger(self):
        """
        Trigger a check of state changes that leads to task execution

        This needs to be called regularly to advance the simulation. If not,
        certain checks for state change will not be called and no new tasks
        will be generated.

        """
        with self._lock:
            found_iteration = 50  # max iterations for safety
            while found_iteration > 0:
                found_new_events = False
                for event in list(self._events):
                    logger.debug("Checking event: {}".format(event))

                    if event:
                        new_events = event.trigger()

                        if new_events:
                            found_new_events = True

                    if not event:
                        # event is finished, clean up
                        idx = self._events.index(event)

                        # TODO: wait for completion
                        del self._events[idx]
                        logger.info('Event finished! Remaining %d' % len(self._events))

                if found_new_events:
                    # if new events or tasks we should re-trigger
                    found_iteration -= 1
                else:
                    found_iteration = 0

            # check worker status and mark as dead if not responding for long times
            now = time.time()
            for w in self.workers:
                if w.state not in ['dead', 'down'] and now - w.seen > self._worker_dead_time:
                    # make sure it will end and not finish any jobs, just in case
                    w.command = 'kill'

                    # and mark it dead
                    w.state = 'dead'

                    # search for abandoned tasks and do something with them
                    if self._set_task_state_from_dead_workers:
                        for t in self.tasks:
                            if t.worker == w and t.state in ['queued', 'running']:
                                t.state = self._set_task_state_from_dead_workers

                    w.current = None

    def run(self):
        """
        Starts observing events in the project

        This is still somehow experimental and will call a background thread to
        call :meth:`Project.trigger` in regular intervals. Make sure to call
        :meth:`Project.stop`
        before you quit the notebook session or exit. Otherwise there might
        be a job in the background left (not confirmed but possible!)

        """
        if not self._event_timer:
            self._stop_event = threading.Event()
            self._event_timer = self.EventTriggerTimer(self._stop_event, self)
            self._event_timer.start()

    def stop(self):
        """
        Stop observing events

        """
        if self._event_timer:
            self._stop_event.set()
            self._event_timer = None
            self._stop_event = None

    def wait_until(self, condition):
        """
        Block until the given condition evaluates to true

        Parameters
        ----------
        condition : callable
            function that is called in regular intervals. If it evaluates to
            True the function returns

        """
        def check_condition(c):
            while not c():
                self.trigger()
                time.sleep(5.0)

        if not isinstance(condition, list):
            condition = [condition]

        [check_condition(c) for c in condition]

    def reload_tasks(self):
        """
        Sychronize the tasks cache by deleting and reloading the
        entire contents.
        """
        self.tasks._set.clear_cache()
        self.tasks._set.load_indices()

    @property
    def task_states(self, deep_check=False):
        """
        Tallies for each task state.
        Returns
        -------
        count of the number of tasks in each observed task state.
        """
        taskstates = dict()
        if deep_check:
            self.tasks._set.clear_cache()
            self.tasks._set.load_indices()

        for task in self.tasks:
            if task.state not in taskstates: taskstates[task.state] = 1
            else: taskstates[task.state] += 1

        return taskstates


    class EventTriggerTimer(threading.Thread):
        """
        A special thread to call the project trigger mechanism

        """
        def __init__(self, event, project):

            super(Project.EventTriggerTimer, self).__init__()
            self.stopped = event
            self.project = project

        def run(self):
            while not self.stopped.wait(5.0):
                self.project.trigger()


class NTrajectories(Condition):
    """
    Condition that triggers if a resource has at least n trajectories present

    """
    def __init__(self, project, number):
        super(NTrajectories, self).__init__()
        self.project = project
        self.number = number

    def check(self):
        return len(self.project.trajectories) >= self.number

    def __str__(self):
        return '#files[%d] >= %d' % (len(self.project.trajectories), self.number)

    def __add__(self, other):
        if isinstance(other, int):
            return NTrajectories(self.project, self.number + other)

        return NotImplemented


class NModels(Condition):
    """
     Condition that triggers if a resource has at least n models present

     """

    def __init__(self, project, number):
        super(NModels, self).__init__()
        self.project = project
        self.number = number

    def check(self):
        return len(self.project.models) >= self.number

    def __str__(self):
        return '#models[%d] >= %d' % (len(self.project.models), self.number)

    def __add__(self, other):
        if isinstance(other, int):
            return NModels(self.project, self.number + other)

        return NotImplemented
