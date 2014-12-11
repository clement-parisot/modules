#######################################################################################################################
# Author: Maxime Schmitt
# Mail: maxime.schmitt@telecom-bretagne.eu
# Overview: Module that take care of managing the configuration files for the various functions of the RESIF suite.
#######################################################################################################################

import os
import sys
import yaml
import time
import re
import subprocess
from git import Repo

#######################################################################################################################
# This functions are wrapper to make the code more readable.
# They shouldn't do much more than calling the bellow functions.
def generateBootstrapConfig(hashTable):
    config = generateCommonConfig(hashTable)

    # Generate some missing configuration informations.
    if not 'releasedir' in config:
        generateReleasedir(config)

    if not 'rootinstall' in config:
        generateRootinstall(config)

    # Expanding apps_root and rootinstall to an absolute path.
    config['apps_root'] = os.path.abspath(config['apps_root'])
    config['rootinstall'] = os.path.abspath(config['rootinstall'])

    # Determining the branches to use for the EasyBuild git repositories
    resolveEBbranches(config)

    # Create the configuration file for EasyBuild.
    easybuildConfigfileCreator(config)
    
    return config

def generateBuildConfig(hashTable):
    config = generateCommonConfig(hashTable)

    # if rootinstall is given, expand it to obtain an abosulte path.
    if 'rootinstall' in config:
        config['rootinstall'] = os.path.abspath(config['rootinstall'])

    # If no file has been given to describe the swsets, we use the default one
    if not 'swsets_config' in config:
        generateSwsetsConfig(config)

    # If no swset is given, the script stops
    if not 'swsets' in config:
        sys.exit('Please specify at least one software set you want to build.\n')

    return config


def generateCleaninstallConfig(hashTable):
    config = generateCommonConfig(hashTable)

    # Generate some missing configuration informations.
    if not 'releasedir' in config:
        generateReleasedir(config)

    if not 'rootinstall' in config:
        generateRootinstall(config)

    # Expanding apps_root and rootinstall to an absolute path.
    config['apps_root'] = os.path.abspath(config['apps_root'])
    config['rootinstall'] = os.path.abspath(config['rootinstall'])

    # Determining the branches to use for the EasyBuild git repositories
    resolveEBbranches(config)

    # Create the configuration file for EasyBuild.
    easybuildConfigfileCreator(config)

    # If no file has been given to describe the swsets, we use the default one
    if not 'swsets_config' in config:
        generateSwsetsConfig(config)

    # If no swset is given, the script stops
    if not 'swsets' in config:
        sys.exit('Please specify at least one software set you want to build.\n')

    # For the build to install everything inside the rootinstall, we set out_place to False
    config['out_place'] = False

    return config

#######################################################################################################################


#######################################################################################################################
# Utilities functions (move to a separate module ?)

# Encode all the field of a dict to a given encoding (Suppose all the fields are strings or tuples of strings).
def encoder(hashTable, encoding):
    for k,v in hashTable.iteritems():
        if isinstance(v, tuple):
            x = ()
            for s in v:
                if isinstance(s, basestring):
                    x += (s.encode(encoding),)
            hashTable[k] = x
        else:
            if v != None and isinstance(v, basestring):
                hashTable[k] = v.encode(encoding)
    return hashTable


# Merge two dict into one (the first one).
def configMerger(default, user):
    if isinstance(default,dict) and isinstance(user,dict):
        for k,v in user.iteritems():
            if v != None and v != ():
                default[k] = v


# Take the path to a YAML file that contains the configuration and return a dict containing the associated config.
def configParser(configFile):
    #repo stream = file(configFile)
    config = yaml.load(configFile)

    for k in ['swsets']:
        if k in config:
            tup = ()
            for v in config[k]:
                tup += (v,)
            config[k] = tup
    
    return config


# Take a dict and expands any environment contained in its fields.
def configExpandVars(hashTable):
    for k,v in hashTable.iteritems():
        if isinstance(v, tuple):
            tup = ()
            for s in v:
                if isinstance(s, basestring):
                    tup += (os.path.expandvars(s),)
            hashTable[k] = tup
        else:
            if v != None and isinstance(v, basestring):
                hashTable[k] = os.path.expandvars(v)

#######################################################################################################################


#######################################################################################################################
# This functions do the actual work in building the configuration.

# Generate the configuration for all the scenarios until differentiation is needed.
def generateCommonConfig(hashTable):
    # We load all configuration made by the user (through a configuration file or the options/environment variables)
    if hashTable['configfile'] != None:
        with open(os.path.join(os.getcwd(),os.path.expandvars(hashTable['configfile'])), "r") as f:
            userConfig = configParser(f)
        configMerger(userConfig, encoder(hashTable, 'utf8'))
    else:
        userConfig = {} # Trick to get rid of all the 'None' values
        configMerger(userConfig, encoder(hashTable, 'utf8'))

    # Environment variables are already managed through Click (envvar entry in the options)

    # If the the "srcpath" key has not been defined in the dict through one of the previous ways, we assume that it has its default value
    if not "srcpath" in userConfig:
        userConfig['srcpath'] = '$HOME/.resif/src'

    try:
        repo = Repo(userConfig['srcpath'])
    except Exception:
        sys.exit("Invalid git repository at " + userConfig['srcpath'])

    # If a a branch or a release has been given, we change the state of the repository accordingly, if not, we use the production branch
    if 'release' in userConfig or 'branch' in userConfig:
        if 'release' in userConfig:
            tree = repo.commit(userConfig['release']).tree
        else:
            tree = repo.heads[userConfig['branch']].commit.tree
    else:
        tree = repo.commit('HEAD').tree

    # We load the default config file and use it to complete the configuration given by the user
    defaultConfigFile = tree['config/config.yaml'].data_stream.read()
    config = configParser(defaultConfigFile)
    configMerger(config, userConfig)

    # Expanding all the environment variables (if any)
    configExpandVars(config)

    # Make srcpath an absolute path
    config['srcpath'] = os.path.abspath(config['srcpath'])

    # Replace short names for the MNS with the real values
    expandMNS(config)

    # Adding the repo and the tree to the config
    config['git_repo'] = repo
    config['git_tree'] = tree

    return config


# Generate a value for the releasedir field of the dict.
def generateReleasedir(hashTable):
    # If we build the HEAD of a branch, we have to find out which branch it is
    if hashTable['release'] == 'HEAD':
        # if a branch is provided, we use it
        if 'branch' in hashTable:
            branch = hashTable['branch']
        # if not provided, we use the one pointed by HEAD.
        else:
            branch = hashTable['git_repo'].active_branch.name

        tree = hashTable['git_repo'].heads[branch].commit.tree #repo
        release = tree['VERSION'].data_stream.read().splitlines()[0]
        shortVersion = re.match('[0-9]*\.[0-9]*', release).group(0)
        hashTable['releasedir'] = os.path.join(branch, 'v' + shortVersion + '-' + time.strftime("%Y%m%d"))
    # If we have been given a more specific release, the branch doesn't matter and we proceed directly
    else:
        # But if we were provided a branch, if the branch really is the branch of the release, we wil build in the corresponding <branch> directory
        if 'branch' in hashTable:
            branch = hashTable['branch']
            tree = hashTable['git_repo'].commit(hashTable['release']).tree
            # If the branch given isn't the same as the branch of the given release, we don't go any further
            commitBranches = subprocess.check_output(['git', 'branch', '--contains', hashTable['release']]).split("\n")
            if not any(True for line in commitBranches if re.search("[^\s]*$", line).group(0) == branch):
                sys.exit("\nThe release you want to build is not part of the branch you have given.\n")
            release = tree['VERSION'].data_stream.read().splitlines()[0]
            shortVersion = re.match('[0-9]*\.[0-9]*', release).group(0)
            hashTable['releasedir'] = os.path.join(branch, 'v' + shortVersion + '-' + time.strftime("%Y%m%d"))
        # if not provided, then we find out if we build a tag or a commit and build in the appropriate directory
        else:
            tagRegex = 'v?[0-9]*\.[0-9]*\.[0-9]*'
            branch = 'tag'
            # VERSION-{tag, SHA1}
            tree = hashTable['git_repo'].commit(hashTable['release']).tree
            release = tree['VERSION'].data_stream.read().splitlines()[0]
            if re.match(tagRegex, hashTable['release']):
                hashTable['releasedir'] = os.path.join(branch, 'v' + release + '-' + hashTable['release'])
            else:
                commit = hashTable['release'][:7]
                hashTable['releasedir'] = os.path.join(branch, 'v' + release + '-' + commit)


# Generate a value for the rootinstall field of the dict.
def generateRootinstall(hashTable):
    if any(True for x in ['gh_ebuser', 'git_ebframework', 'git_ebblocks', 'git_ebconfigs'] if x in hashTable):
        hashTable['rootinstall'] = os.path.join(hashTable['apps_root'], hashTable['releasedir'] + '_alt.sources')
    else:
    	hashTable['rootinstall'] = os.path.join(hashTable['apps_root'], hashTable['releasedir'])


# Generate a value for the swsets_config field of the dict.
def generateSwsetsConfig(hashTable):
	hashTable['swsets_config'] = os.path.join(os.path.join(hashTable['srcpath'], 'config'), 'swsets.yaml')


# Get the version of EasyBuild installed in the <rootdirectory>/EasyBuild directory
def getEasyBuildVersion(rootdirectory):
	# We make sure that the path given is totally expanded.
	absrootdirectory = os.path.abspath(os.path.expandvars(rootdirectory))
	# Appending to path the EasyBuild directories (temporarily)
	sys.path.insert(0, os.path.join(os.path.join(absrootdirectory, '.installRef'), 'easybuild-framework'))
	sys.path.insert(0, os.path.join(os.path.join(absrootdirectory, '.installRef'), 'easybuild-easyblocks'))
	sys.path.insert(0, os.path.join(os.path.join(absrootdirectory, '.installRef'), 'easybuild-easyconfigs'))

	# Importing the function that EasyBuild uses to determnine its own version
	from easybuild.tools.version import this_is_easybuild

	# Getting the version of EasyBuild from the output message
	msg = this_is_easybuild()
	version = re.search("[0-9]*\.[0-9]*\.[0-9]*", msg).group(0)

	# Removing from path the EasyBuild directories (cleanup)
	sys.path.pop(0)
	sys.path.pop(0)
	sys.path.pop(0)

	return version


# Generate a config file for EasyBuild
def easybuildConfigfileCreator(hashTable):
    trueVersion = os.path.basename(hashTable['rootinstall'])
    path = os.path.join(hashTable['srcpath'], 'config') # <srcpath>/config
    repository = 'FileRepository'
    logfile_format = ('easylog', 'easybuild-%(name)s-%(version)s-%(date)s.%(time)s.log')

    ebdirsOnPlace = os.path.join(hashTable['rootinstall'], '.ebdirs') # <rootinstall>/.ebdirs
    sourcepathOnPlace = os.path.join(ebdirsOnPlace, 'sources') # <rootinstall>/.ebdirs/sources
    buildpathOnPlace = os.path.join(ebdirsOnPlace, 'build') # <rootinstall>/.ebdirs/build
    repositorypathOnPlace = os.path.join(ebdirsOnPlace, 'eb_repo') # <rootinstall>/.ebdirs/eb_repo

    ebdirsOutPlace = os.path.join(os.path.join('$HOME' ,'.resif'), trueVersion) # $HOME/.resif/vx.y-YYYYMMDD/
    sourcepathOutPlace = os.path.join(ebdirsOutPlace, 'sources') # $HOME/.resif/vx.y-YYYYMMDD/sources
    buildpathOutPlace = os.path.join(ebdirsOutPlace, 'build') # $HOME/.resif/vx.y-YYYYMMDD/build
    repositorypathOutPlace = os.path.join(ebdirsOutPlace, 'eb_repo') # $HOME/.resif/vx.y-YYYYMMDD/eb_repo

    with open(os.path.join(path, 'easybuild.cfg'), 'w') as f:
        f.write('[config]\n')
        f.write('sourcepath = ' + sourcepathOnPlace + '\n')
        f.write('buildpath = ' + buildpathOnPlace + '\n')
        f.write('repository = ' + repository + '\n')
        f.write('repositorypath = ' + repositorypathOnPlace + '\n')
        f.write('module-naming-scheme = ' + hashTable['mns'] +'\n')
        # Currenctly, this option isn't working (EasyBuild 1.15.2) so we don't use it until it is fixed.
        f.write('#logfile-format = ' + logfile_format[0] + ',' + logfile_format[1] + '\n')

    with open(os.path.join(path, 'easybuild-out-place.cfg'), 'w') as f:
        f.write('[config]\n')
        f.write('sourcepath = ' + sourcepathOutPlace + '\n')
        f.write('buildpath = ' + buildpathOutPlace + '\n')
        f.write('repository = ' + repository + '\n')
        f.write('repositorypath = ' + repositorypathOutPlace + '\n')
        f.write('module-naming-scheme = ' + hashTable['mns'] +'\n')
        # Currenctly, this option isn't working (EasyBuild 1.15.2) so we don't use it until it is fixed.
        f.write('#logfile-format = ' + logfile_format[0] + ',' + logfile_format[1] + '\n')


# Find the name of the EasyBuild module that should be loaded depending on the MNS.
def getEasyBuildModule(hashTable):
    if hashTable['mns'] == 'ThematicMNS':
        return "base/EasyBuild/install-" + getEasyBuildVersion(hashTable['rootinstall'])
    else:
        return 'EasyBuild/install-' + getEasyBuildVersion(hashTable['rootinstall'])

def setEasyBuildVariables(hashTable):
    ebdirsRoot = os.path.join(hashTable['rootinstall'], '.ebdirs') # <rootinstall>/.ebdirs
    if not os.path.exists(ebdirsRoot):
            os.makedirs(ebdirsRoot)

    hashTable['eb_sourcepath'] = os.path.join(ebdirsRoot, 'sources')
    hashTable['eb_buildpath'] = os.path.join(ebdirsRoot, 'build')
    hashTable['eb_repository'] = 'FileRepository'
    hashTable['eb_repositorypath'] = os.path.join(ebdirsRoot, 'eb_repo')

def expandMNS(hashTable):
    if hashTable['mns'] == 'E':
        hashTable['mns'] = 'EasyBuildMNS'
    if hashTable['mns'] == 'H':
        hashTable['mns'] = 'HierarchicalMNS'
    if hashTable['mns'] == 'T':
        hashTable['mns'] = 'ThematicMNS'

def resolveEBbranches(hashTable):
    for repo in ['framework', 'blocks', 'configs']:
        if 'git_eb'+repo in hashTable:
            gitUrl = re.search("^[^|]*", hashTable['git_eb'+repo]).group(0)
            gitBranch = re.search("[^|]*$", hashTable['git_eb'+repo]).group(0)
            hashTable['git_eb'+repo] = gitUrl
            # We set the correct branch if any has been given (priority is given to the branch-eb* option)
            if not 'branch_eb'+repo in hashTable and gitUrl != gitBranch:
                hashTable['branch_eb'+repo] = gitBranch

#######################################################################################################################