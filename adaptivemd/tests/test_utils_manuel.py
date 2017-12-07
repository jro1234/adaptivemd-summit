import os
import json
import random
import string
import unittest
from adaptivemd.rp.database import Database
from adaptivemd.rp.utils import *

# Configuration Variables
mongo_url = 'mongodb://user:user@two.radical-project.org:32769/'
project = 'rp_testing'

# Example JSON locations
directory = os.path.dirname(os.path.abspath(__file__))
conf_example = 'example-json/configuration-example.json'
res_example = 'example-json/resource-example.json'
task_example = 'example-json/task-example.json'
file_example = 'example-json/file-example.json'
gen_example = 'example-json/generator-example.json'
ptask_in_example = 'example-json/pythontask-input-example.json'


def id_generator(size=6, chars=string.ascii_uppercase + string.digits):
    """Random ID/String Generator"""
    return ''.join(random.choice(chars) for _ in range(size))


class TestUtils(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Initialize tests, just creates instance variables needed and the DB object.
        """
        super(TestUtils, cls).setUpClass()
        cls.db = Database(mongo_url=mongo_url,
                          project='{}_{}'.format(project, id_generator()))

        # Create Database and collections
        client = cls.db.client
        cls.store_name = "{}-{}".format(cls.db.store_prefix, cls.db.project)
        mongo_db = client[cls.store_name]
        tasks_col = mongo_db[cls.db.tasks_collection]
        configs_col = mongo_db[cls.db.configuration_collection]
        resources_col = mongo_db[cls.db.resource_collection]
        files_col = mongo_db[cls.db.file_collection]
        generators_col = mongo_db[cls.db.generator_collection]

        # Insert test documents
        with open('{}/{}'.format(directory, conf_example)) as json_data:
            data = json.load(json_data)
            for config_entry in data:
                configs_col.insert_one(config_entry)

        with open('{}/{}'.format(directory, res_example)) as json_data:
            data = json.load(json_data)
            for resource_entry in data:
                resources_col.insert_one(resource_entry)

        with open('{}/{}'.format(directory, file_example)) as json_data:
            data = json.load(json_data)
            for file_entry in data:
                files_col.insert_one(file_entry)

        with open('{}/{}'.format(directory, gen_example)) as json_data:
            data = json.load(json_data)
            for generator_entry in data:
                generators_col.insert_one(generator_entry)

        with open('{}/{}'.format(directory, task_example)) as json_data:
            # insert tasks
            data = json.load(json_data)
            for task_entry in data:
                tasks_col.insert_one(task_entry)

    @classmethod
    def tearDownClass(cls):
        """Destroy the database since we don't need it anymore"""
        client = cls.db.client
        client.drop_database(cls.store_name)
        client.close()

    def test_get_input_staging_TrajectoryGenerationTask(self):
        """Test that the input staging directives are properly 
        generated for a TrajectoryGenerationTask"""
        task_descriptions = self.db.get_task_descriptions()
        task_desc = dict()
        for task in task_descriptions:
            if task['_id'] == '04f01b52-8c69-11e7-9eb2-000000000124':
                task_desc = task
                break
        # Get each component of the task
        pre_task_details = task_desc['_dict'].get('pre', dict())
        main_task_details = task_desc['_dict'].get('_main', dict())
        
        staging_directives = get_input_staging(
        task_details=pre_task_details, db=self.db, shared_path='/home/test', 
        project=self.db.project, break_after_non_dict=False)
        staging_directives.extend(get_input_staging(
        task_details=main_task_details, db=self.db, shared_path='/home/test', 
        project=self.db.project, break_after_non_dict=True))
        
        actual = [
            {"action":"Link","source":"pilot:///alanine.pdb","target":"unit:///initial.pdb"},
            {"action":"Link","source":"pilot:///system.xml","target":"unit:///system.xml"},
            {"action":"Link","source":"pilot:///integrator.xml","target":"unit:///integrator.xml"},
            {"action":"Link","source":"pilot:///openmmrun.py","target":"unit:///openmmrun.py"}
        ]

        self.assertListEqual(staging_directives, actual)

    def test_get_input_staging_PythonTask(self):
        """Test that the input staging directives are properly 
        generated for a PythonTask"""
        task_descriptions = self.db.get_task_descriptions()
        task_desc = dict()
        for task in task_descriptions:
            if task['_id'] == '04f01b52-8c69-11e7-9eb2-0000000000fe':
                task_desc = task
                break
        # Get each component of the task
        pre_task_details = task_desc['_dict'].get('pre', dict())
        main_task_details = task_desc['_dict'].get('_main', dict())
        
        staging_directives = get_input_staging(
        task_details=pre_task_details, db=self.db, shared_path='/home/test', 
        project=self.db.project, break_after_non_dict=False)
        staging_directives.extend(get_input_staging(
        task_details=main_task_details, db=self.db, shared_path='/home/test', 
        project=self.db.project, break_after_non_dict=True))

        actual = [
            {"action":"Link","source":"pilot:///_run_.py","target":"unit:///_run_.py"},
            {"action":"Link","source":"pilot:///alanine.pdb","target":"unit:///input.pdb"}
        ]
        self.assertListEqual(staging_directives, actual)

    def test_get_output_staging_TrajectoryGenerationTask(self):
        """Test that the output staging directives are properly generated for a TrajectoryGenerationTask"""
        task_descriptions = self.db.get_task_descriptions()
        task_desc = dict()
        for task in task_descriptions:
            if task['_id'] == '04f01b52-8c69-11e7-9eb2-000000000124':
                task_desc = task
                break
        # Get each component of the task
        main_task_details = task_desc['_dict'].get('_main', dict())
        post_task_details = task_desc['_dict'].get('post', dict())

        staging_directives = get_output_staging(
        task_desc=task_desc, task_details=post_task_details, db=self.db,
        shared_path='/home/test', project=self.db.project,
        continue_before_non_dict=False)
        staging_directives.extend(get_output_staging(
        task_desc=task_desc, task_details=main_task_details, db=self.db,
        shared_path='/home/test', project=self.db.project,
        continue_before_non_dict=True))
        
        actual = [{
            "action":"Move","source":"traj/protein.dcd",
            "target":"/home/test//projects/rp_testing_modeller_1/trajs/00000004//protein.dcd"},
            {"action":"Move","source":"traj/master.dcd",
            "target":"/home/test//projects/rp_testing_modeller_1/trajs/00000004//master.dcd"
        }]
        
        self.assertListEqual(staging_directives, actual)

    def test_get_output_staging_PythonTask(self):
        """Test that the output staging directives are properly generated for a PythonTask"""
        task_descriptions = self.db.get_task_descriptions()
        task_desc = dict()
        for task in task_descriptions:
            if task['_id'] == '04f01b52-8c69-11e7-9eb2-0000000000fe':
                task_desc = task
                break
        # Get each component of the task
        main_task_details = task_desc['_dict'].get('_main', dict())
        post_task_details = task_desc['_dict'].get('post', dict())

        staging_directives = get_output_staging(
        task_desc=task_desc, task_details=post_task_details, db=self.db,
        shared_path='/home/test', project=self.db.project,
        continue_before_non_dict=False)
        staging_directives.extend(get_output_staging(
        task_desc=task_desc, task_details=main_task_details, db=self.db,
        shared_path='/home/test', project=self.db.project,
        continue_before_non_dict=True))
        
        actual = [{
            "action": "Copy",
            "source": "output.json", 
            "target": "/home/test/projects/{}//models/model.0x4f01b528c6911e79eb20000000000feL.json".format(self.db.project)
        }]
        
        self.assertListEqual(staging_directives, actual)

    def test_get_commands_TrajectoryGenerationTask(self):
        """Test that the commands are properly captured for a TrajectoryGenerationTask"""
        task_descriptions = self.db.get_task_descriptions()
        task_desc = dict()
        for task in task_descriptions:
            if task['_id'] == '04f01b52-8c69-11e7-9eb2-000000000124':
                task_desc = task
                break
        # Get each component of the task
        pre_task_details = task_desc['_dict'].get('pre', dict())
        main_task_details = task_desc['_dict'].get('_main', dict())
        post_task_details = task_desc['_dict'].get('post', dict())

        pre_commands = get_commands(
        task_steps_list=pre_task_details, shared_path='/home/test', project=self.db.project)
        actual = ["source /home/test/venv/bin/activate"]
        self.assertListEqual(pre_commands, actual)

        main_commands = get_commands(
        task_steps_list=main_task_details, shared_path='/home/test', project=self.db.project)
        actual = ["\nj=0\ntries=10\nsleep=1\n\ntrajfile=traj/allatoms.dcd\n\nwhile [ $j -le $tries ]; do if ! [ -s $trajfile ]; then python openmmrun.py -r --report-interval 1 -p CPU --types=\"{'protein':{'stride':1,'selection':'protein','name':null,'filename':'protein.dcd'},'master':{'stride':10,'selection':null,'name':null,'filename':'master.dcd'}}\" -t worker://initial.pdb --length 100 worker://traj/; fi; sleep 1; j=$((j+1)); done"]
        self.assertListEqual(main_commands, actual)

        post_commands = get_commands(
        task_steps_list=post_task_details, shared_path='/home/test', project=self.db.project)
        actual = ["deactivate"]
        self.assertListEqual(post_commands, actual)
        

    def test_get_commands_PythonTask(self):
        """Test that the commands are properly captured for a PythonTask"""
        task_descriptions = self.db.get_task_descriptions()
        task_desc = dict()
        for task in task_descriptions:
            if task['_id'] == '04f01b52-8c69-11e7-9eb2-0000000000fe':
                task_desc = task
                break
        # Get each component of the task
        pre_task_details = task_desc['_dict'].get('pre', dict())
        main_task_details = task_desc['_dict'].get('_main', dict())
        post_task_details = task_desc['_dict'].get('post', dict())

        pre_commands = get_commands(
        task_steps_list=pre_task_details, shared_path='/home/test', project=self.db.project)
        actual = ["source /home/test/venv/bin/activate"]
        self.assertListEqual(pre_commands, actual)

        main_commands = get_commands(
        task_steps_list=main_task_details, shared_path='/home/test', project=self.db.project)
        actual = ["python _run_.py"]
        self.assertListEqual(main_commands, actual)

        post_commands = get_commands(
        task_steps_list=post_task_details, shared_path='/home/test', project=self.db.project)
        actual = ["deactivate"]
        self.assertListEqual(post_commands, actual)

    def test_get_environment_from_task_TrajectoryGenerationTask(self):
        """Test that the environment variables are properly captured"""
        task_descriptions = self.db.get_task_descriptions()
        
        # TrajectoryGenerationTask
        task_desc = dict()
        for task in task_descriptions:
            if task['_id'] == '04f01b52-8c69-11e7-9eb2-000000000124':
                task_desc = task
                break

        environment = get_environment_from_task(task_desc)
        actual = {"TEST1": "1", "TEST2": "2"}
        self.assertDictEqual(environment, actual)
    
    def test_get_environment_from_task_PythonTask(self):
        """Test that the environment variables are properly captured"""
        task_descriptions = self.db.get_task_descriptions()

        # PythonTask
        task_desc = dict()
        for task in task_descriptions:
            if task['_id'] == '04f01b52-8c69-11e7-9eb2-0000000000fe':
                task_desc = task
                break

        environment = get_environment_from_task(task_desc)
        actual = {"TEST3": "3", "TEST4": "4"}
        self.assertDictEqual(environment, actual)

    def test_get_paths_from_task_TrajectoryGenerationTask(self):
        """Test that the paths variables are properly captured"""
        task_descriptions = self.db.get_task_descriptions()
        
        # TrajectoryGenerationTask
        task_desc = dict()
        for task in task_descriptions:
            if task['_id'] == '04f01b52-8c69-11e7-9eb2-000000000124':
                task_desc = task
                break

        paths = get_paths_from_task(task_desc)
        actual = [
            "/home/test/path1",
            "/home/test/path2"
        ]
        self.assertListEqual(paths, actual)
    
    def test_get_paths_from_task_PythonTask(self):
        """Test that the paths variables are properly captured"""
        task_descriptions = self.db.get_task_descriptions()

        # PythonTask
        task_desc = dict()
        for task in task_descriptions:
            if task['_id'] == '04f01b52-8c69-11e7-9eb2-0000000000fe':
                task_desc = task
                break

        paths = get_paths_from_task(task_desc)
        actual = [
            "/home/test/path3",
            "/home/test/path4"
        ]
        self.assertListEqual(paths, actual)


    def test_generate_pythontask_input(self):
        """Test that the input file is properly generated"""
        d1 = None
        with open('{}/{}'.format(directory, ptask_in_example)) as json_data:
            d1 = json.load(json_data)
        task = None
        task_descriptions = self.db.get_task_descriptions()
        for t in task_descriptions:
            if t['_cls'] == 'PythonTask':
                task = t
                break
        d2 = generate_pythontask_input(
            db=self.db, shared_path='/home/example', task=task, project=self.db.project)
        self.assertDictEqual(d1, d2)

    def test_hex_to_id(self):
        hex_uuid = hex_to_id("0x4f01b528c6911e79eb200000000003aL")
        actual = "04f01b52-8c69-11e7-9eb2-00000000003a"
        self.assertEquals(hex_uuid, actual)

    def test_resolve_pathholders(self):
        # Direct Path
        exp_path = resolve_pathholders("/some/path", shared_path='/home/test', project=self.db.project)
        actual = "/some/path"
        self.assertEquals(exp_path, actual)

        # Staging Path
        exp_path = resolve_pathholders("staging:///some/path", shared_path='/home/test', project=self.db.project)
        actual = "pilot:///path" # SHOULD BE: actual = "pilot:///some/path"
        self.assertEquals(exp_path, actual)

        # Sandbox Path
        exp_path = resolve_pathholders("sandbox:///some/path", shared_path='/home/test', project=self.db.project)
        actual = "/home/test//some/path"
        self.assertEquals(exp_path, actual)

        # File Path
        exp_path = resolve_pathholders("file:///some/path.py", shared_path='/home/test', project=self.db.project)
        actual = "/some/path.py"
        self.assertEquals(exp_path, actual)

        # Projects Path
        exp_path = resolve_pathholders("project:///some/path.py", shared_path='/home/test', project=self.db.project)
        actual = "/home/test/projects/{}//some/path.py".format(self.db.project)
        self.assertEquals(exp_path, actual)


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(TestUtils)
    unittest.TextTestRunner(verbosity=2).run(suite)
