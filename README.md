[![Build Status](https://travis-ci.org/markovmodel/adaptivemd.svg?branch=devel)](https://travis-ci.org/markovmodel/adaptivemd)

# AdaptiveMD

This version works via a set of fast fixes hardcoded in the source that are specific
to using OLCF Summit and Rhea together to execute AdaptiveMD workflows. 

MDTraj and PyEMMA are not fully functional on Summit, so Rhea is used to perform
analysis tasks. There are many bugs and quirks to how this setup works, but it
should execute workflow faithfully when they are configured correctly. 

BEFORE you run this, you will need to find a copy of the ppc64le MongoDB software
AND bring it into you PATH variable on Summit:
`export PATH="/path/to/your/mongo-ppc64le/bin/:$PATH"`

This is a 2-part install, first we will do the Summit source code, then Rhea. After you
run this `export`, you are ready to install AdaptiveMD on OLCF Summit.

## 1. Install
## 1.1 SUMMIT
1. Go to your project allocation's data directory
2. Clone this repo: `git clone https://github.com/jrossyra/adaptivemd-summit`
2. `vim install.bash`
2.1 Alter disk locations at top of file according to your allocation specifics.
    If you want, you can make it a group or individual install by altering the
    USER variable's folder setup, and adjusting your installations' permissions
    according to your preference. The workflow runtime and project data are
    separately controlled in this directory-specification setup, which are
    independently set in this install file to user or group level paths.
2.2 Double check that all the versions you will use are correct.. e.g. the CUDA
    module matches the load statement & OpenMM tag. If you must unload a Python
    or any other interfering modules, they should be written into your installer
    via your or your admin's discretion.
2.3 You will have a `bashrc` file to load this AdaptiveMD environment at the path
    given by `ADMD_PROFILE`. Source this file to use AdaptiveMD on Summit after
    you install. 
3. `./install.bash`
4. You should run the weak scaling experiment workflow to make sure everyting
   performs according to your (reasonable) expectations on your HPC or cluster
   resource.

## 1.2 RHEA
1. Clone this repo
