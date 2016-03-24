# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from builtins import str

import uuid, filecmp, os, sys, requests, tempfile, time
from datetime import datetime as Datetime
from nose.tools import assert_raises
from nose.plugins.attrib import attr
from mock import patch
try:
    import configparser
except ImportError:
    import ConfigParser as configparser

import synapseclient
import synapseclient.client as client
import synapseclient.utils as utils
from synapseclient import Activity, Entity, Project, Folder, File, Link
from synapseclient.exceptions import *

import integration
from integration import schedule_for_cleanup


def setup(module):
    print('\n')
    print('~' * 60)
    print(os.path.basename(__file__))
    print('~' * 60)
    module.syn = integration.syn
    module.project = integration.project

    # Some of these tests require a second user
    config = configparser.ConfigParser()
    config.read(synapseclient.client.CONFIG_FILE)
    module.other_user = {}
    try:
        other_user['username'] = config.get('test-authentication', 'username')
        other_user['password'] = config.get('test-authentication', 'password')
        other_user['principalId'] = config.get('test-authentication', 'principalId')
    except configparser.Error:
        print("[test-authentication] section missing from the configuration file")

    if 'principalId' not in other_user:
        # Fall back on the synapse-test user
        other_user['principalId'] = 1560252
        other_user['username'] = 'synapse-test'


def test_Entity():
    # Update the project
    project_name = str(uuid.uuid4())
    project = Project(name=project_name)
    project = syn.store(project)
    schedule_for_cleanup(project)
    project = syn.getEntity(project)
    assert project.name == project_name
    
    # Create and get a Folder
    folder = Folder('Test Folder', parent=project, description='A place to put my junk', foo=1000)
    folder = syn.createEntity(folder)
    folder = syn.getEntity(folder)
    assert folder.name == 'Test Folder'
    assert folder.parentId == project.id
    assert folder.description == 'A place to put my junk'
    assert folder.foo[0] == 1000
    
    # Update and get the Folder
    folder.pi = 3.14159265359
    folder.description = 'The rejects from the other folder'
    folder = syn.store(folder)
    folder = syn.get(folder)
    assert folder.name == 'Test Folder'
    assert folder.parentId == project.id
    assert folder.description == 'The rejects from the other folder'
    assert folder.pi[0] == 3.14159265359

    # Test CRUD on Files, check unicode
    path = utils.make_bogus_data_file()
    schedule_for_cleanup(path)
    a_file = File(path, parent=folder, description=u'Description with funny characters: Déjà vu, ประเทศไทย, 中国',
                  contentType='text/flapdoodle',
                  foo='An arbitrary value',
                  bar=[33,44,55],
                  bday=Datetime(2013,3,15),
                  band=u"Motörhead",
                  lunch=u"すし")
    a_file = syn.store(a_file)
    assert a_file.path == path

    a_file = syn.getEntity(a_file)
    assert a_file.description == u'Description with funny characters: Déjà vu, ประเทศไทย, 中国', u'description= %s' % a_file.description
    assert a_file['foo'][0] == 'An arbitrary value', u'foo= %s' % a_file['foo'][0]
    assert a_file['bar'] == [33,44,55]
    assert a_file['bday'][0] == Datetime(2013,3,15)
    assert a_file.contentType == 'text/flapdoodle', u'contentType= %s' % a_file.contentType
    assert a_file['band'][0] == u"Motörhead", u'band= %s' % a_file['band'][0]
    assert a_file['lunch'][0] == u"すし", u'lunch= %s' % a_file['lunch'][0]
    
    a_file = syn.downloadEntity(a_file)
    assert filecmp.cmp(path, a_file.path)

    assert_raises(ValueError,File,a_file.path,parent=folder,dataFileHandleId=56456)
    b_file = File(name="blah",parent=folder,dataFileHandleId=a_file.dataFileHandleId)
    b_file = syn.store(b_file)

    assert b_file.dataFileHandleId == a_file.dataFileHandleId
    # Update the File
    a_file.path = path
    a_file['foo'] = 'Another arbitrary chunk of text data'
    a_file['new_key'] = 'A newly created value'
    a_file = syn.updateEntity(a_file)
    assert a_file['foo'][0] == 'Another arbitrary chunk of text data'
    assert a_file['bar'] == [33,44,55]
    assert a_file['bday'][0] == Datetime(2013,3,15)
    assert a_file.new_key[0] == 'A newly created value'
    assert a_file.path == path
    assert a_file.versionNumber == 1, "unexpected version number: " +  str(a_file.versionNumber)

    #Test create, store, get Links
    link = Link(a_file['id'], 
                targetVersion=a_file.versionNumber,
                parent=project)
    link = syn.store(link)
    assert link['linksTo']['targetId'] == a_file['id']
    assert link['linksTo']['targetVersionNumber'] == a_file.versionNumber
    assert link['linksToClassName'] == a_file['concreteType']
    
    testLink = syn.get(link)
    assert testLink == link

    link = syn.get(link,followLink= True)
    assert link['foo'][0] == 'Another arbitrary chunk of text data'
    assert link['bar'] == [33,44,55]
    assert link['bday'][0] == Datetime(2013,3,15)
    assert link.new_key[0] == 'A newly created value'
    assert utils.equal_paths(link.path, path)
    assert link.versionNumber == 1, "unexpected version number: " +  str(a_file.versionNumber)

    # Upload a new File and verify
    new_path = utils.make_bogus_data_file()
    schedule_for_cleanup(new_path)
    a_file = syn.uploadFile(a_file, new_path)
    a_file = syn.downloadEntity(a_file)
    assert filecmp.cmp(new_path, a_file.path)
    assert a_file.versionNumber == 2

    # Make sure we can still get the older version of file
    old_random_data = syn.get(a_file.id, version=1)
    assert filecmp.cmp(old_random_data.path, path)

    tmpdir = tempfile.mkdtemp()
    schedule_for_cleanup(tmpdir)

    ## test file name override
    a_file.fileNameOverride = "peaches_en_regalia.zoinks"
    syn.store(a_file)
    ## TODO We haven't defined how filename override interacts with
    ## TODO previously cached files so, side-step that for now by
    ## TODO making sure the file is not in the cache!
    syn.cache.remove(a_file.dataFileHandleId, delete=True)
    a_file_retreived = syn.get(a_file, downloadLocation=tmpdir)
    assert os.path.basename(a_file_retreived.path) == a_file.fileNameOverride, os.path.basename(a_file_retreived.path)

    ## test getting the file from the cache with downloadLocation parameter (SYNPY-330)
    a_file_cached = syn.get(a_file.id, downloadLocation=tmpdir)
    assert a_file_cached.path is not None
    assert os.path.basename(a_file_cached.path) == a_file.fileNameOverride, a_file_cached.path

    print("\n\nList of files in project:\n")
    syn._list(project, recursive=True)


def test_special_characters():
    folder = syn.store(Folder(u'Special Characters Here',
        parent=project,
        description=u'A test for special characters such as Déjà vu, ประเทศไทย, and 中国',
        hindi_annotation=u'बंदर बट',
        russian_annotation=u'Обезьяна прикладом',
        weird_german_thing=u'Völlerei lässt grüßen'))
    assert folder.name == u'Special Characters Here'
    assert folder.parentId == project.id
    assert folder.description == u'A test for special characters such as Déjà vu, ประเทศไทย, and 中国', u'description= %s' % folder.description
    assert folder.weird_german_thing[0] == u'Völlerei lässt grüßen'
    assert folder.hindi_annotation[0] == u'बंदर बट'
    assert folder.russian_annotation[0] == u'Обезьяна прикладом'


def test_get_local_file():
    new_path = utils.make_bogus_data_file()
    schedule_for_cleanup(new_path)
    folder = Folder('TestFindFileFolder', parent=project, description='A place to put my junk')
    folder = syn.createEntity(folder)

    #Get an nonexistent file in Synapse
    assert_raises(SynapseError, syn.get, new_path)

    #Get a file really stored in Synapse
    ent_folder = syn.store(File(new_path, parent=folder))
    ent2 = syn.get(new_path)
    assert ent_folder.id==ent2.id and ent_folder.versionNumber==ent2.versionNumber

    #Get a file stored in Multiple locations #should display warning
    ent = syn.store(File(new_path, parent=project))
    ent = syn.get(new_path)

    #Get a file stored in multiple locations with limit set
    ent = syn.get(new_path, limitSearch=folder.id)
    assert ent.id == ent_folder.id and ent.versionNumber==ent_folder.versionNumber

    #Get a file that exists but such that limitSearch removes them and raises error
    assert_raises(SynapseError, syn.get, new_path, limitSearch='syn1')


def test_store_with_flags():
    # -- CreateOrUpdate flag for Projects --
    # If we store a project with the same name, it should become an update
    projUpdate = Project(project.name)
    projUpdate.updatedThing = 'Yep, sho\'nuf it\'s updated!'
    projUpdate = syn.store(projUpdate, createOrUpdate=True)
    assert project.id == projUpdate.id
    assert projUpdate.updatedThing == ['Yep, sho\'nuf it\'s updated!']

    # Store a File
    filepath = utils.make_bogus_binary_file()
    schedule_for_cleanup(filepath)
    origBogus = File(filepath, name='Bogus Test File', parent=project)
    origBogus = syn.store(origBogus, createOrUpdate=True)
    assert origBogus.versionNumber == 1

    # Modify existing annotations by createOrUpdate
    del projUpdate['parentId']
    del projUpdate['id']
    projUpdate.updatedThing = 'Updated again'
    projUpdate.addedThing = 'Something new'
    projUpdate = syn.store(projUpdate, createOrUpdate=True)
    assert project.id == projUpdate.id
    assert projUpdate.updatedThing == ['Updated again']
    
    # -- ForceVersion flag --
    # Re-store the same thing and don't up the version
    mutaBogus = syn.store(origBogus, forceVersion=False)
    assert mutaBogus.versionNumber == 1
    
    # Re-store again, essentially the same condition
    mutaBogus = syn.store(mutaBogus, createOrUpdate=True, forceVersion=False)
    assert mutaBogus.versionNumber == 1, "expected version 1 but got version %s" % mutaBogus.versionNumber
    
    # And again, but up the version this time
    mutaBogus = syn.store(mutaBogus, forceVersion=True)
    assert mutaBogus.versionNumber == 2

    # -- CreateOrUpdate flag for files --
    # Store a different file with the same name and parent
    # Expected behavior is that a new version of the first File will be created
    new_filepath = utils.make_bogus_binary_file()
    schedule_for_cleanup(new_filepath)
    mutaBogus.path = new_filepath
    mutaBogus = syn.store(mutaBogus, createOrUpdate=True)
    assert mutaBogus.id == origBogus.id
    assert mutaBogus.versionNumber == 3
    assert not filecmp.cmp(mutaBogus.path, filepath)

    # Make doubly sure the File was uploaded
    checkBogus = syn.get(mutaBogus.id)
    assert checkBogus.id == origBogus.id
    assert checkBogus.versionNumber == 3
    assert filecmp.cmp(mutaBogus.path, checkBogus.path)

    # Create yet another file with the same name and parent
    # Expected behavior is raising an exception with a 409 error
    newer_filepath = utils.make_bogus_binary_file()
    schedule_for_cleanup(newer_filepath)
    badBogus = File(newer_filepath, name='Bogus Test File', parent=project)
    assert_raises(SynapseHTTPError, syn.store, badBogus, createOrUpdate=False)
    
    # -- Storing after syn.get(..., downloadFile=False) --
    ephemeralBogus = syn.get(mutaBogus, downloadFile=False)
    ephemeralBogus.description = 'Snorklewacker'
    ephemeralBogus.shoe_size = 11.5
    ephemeralBogus = syn.store(ephemeralBogus)

    ephemeralBogus = syn.get(ephemeralBogus, downloadFile=False)
    assert ephemeralBogus.description == 'Snorklewacker'
    assert ephemeralBogus.shoe_size == [11.5]


def test_get_with_downloadLocation_and_ifcollision():
    # Store a File and delete it locally
    filepath = utils.make_bogus_binary_file()
    bogus = File(filepath, name='Bogus Test File', parent=project)
    bogus = syn.store(bogus)
    os.remove(filepath)

    # Compare stuff to this one
    normalBogus = syn.get(bogus)
    
    # Download to the temp folder, should be the same
    otherBogus = syn.get(bogus, downloadLocation=os.path.dirname(filepath))
    assert otherBogus.id == normalBogus.id
    assert filecmp.cmp(otherBogus.path, normalBogus.path)
    
    # Invalidate the downloaded file's timestamps
    os.utime(otherBogus.path, (0, 0))
    badtimestamps = os.path.getmtime(otherBogus.path)
    
    # Download again, should change the modification time
    overwriteBogus = syn.get(bogus, downloadLocation=os.path.dirname(filepath), ifcollision="overwrite.local")
    overwriteModTime = os.path.getmtime(overwriteBogus.path)
    assert badtimestamps != overwriteModTime
    
    # Download again, should not change the modification time
    otherBogus = syn.get(bogus, downloadLocation=os.path.dirname(filepath), ifcollision="keep.local")
    assert overwriteModTime == os.path.getmtime(otherBogus.path)
    
    # Invalidate the timestamps again
    os.utime(otherBogus.path, (0, 0))
    badtimestamps = os.path.getmtime(otherBogus.path)
    
    # Download once more, but rename
    renamedBogus = syn.get(bogus, downloadLocation=os.path.dirname(filepath), ifcollision="keep.both")
    assert otherBogus.path != renamedBogus.path
    assert filecmp.cmp(otherBogus.path, renamedBogus.path)
    
    # Clean up
    os.remove(otherBogus.path)
    os.remove(renamedBogus.path)


def test_store_activity():
    # Create a File and an Activity
    path = utils.make_bogus_binary_file()
    schedule_for_cleanup(path)
    entity = File(path, name='Hinkle horn honking holes', parent=project)
    honking = Activity(name='Hinkle horn honking', 
                       description='Nettlebed Cave is a limestone cave located on the South Island of New Zealand.')
    honking.used('http://www.flickr.com/photos/bevanbfree/3482259379/')
    honking.used('http://www.flickr.com/photos/bevanbfree/3482185673/')

    # This doesn't set the ID of the Activity
    entity = syn.store(entity, activity=honking)

    # But this does
    honking = syn.getProvenance(entity.id)

    # Verify the Activity
    assert honking['name'] == 'Hinkle horn honking'
    assert len(honking['used']) == 2
    assert honking['used'][0]['concreteType'] == 'org.sagebionetworks.repo.model.provenance.UsedURL'
    assert honking['used'][0]['wasExecuted'] == False
    assert honking['used'][0]['url'].startswith('http://www.flickr.com/photos/bevanbfree/3482')
    assert honking['used'][1]['concreteType'] == 'org.sagebionetworks.repo.model.provenance.UsedURL'
    assert honking['used'][1]['wasExecuted'] == False

    # Store another Entity with the same Activity
    entity = File('http://en.wikipedia.org/wiki/File:Nettlebed_cave.jpg', 
                  name='Nettlebed Cave', parent=project, synapseStore=False)
    entity = syn.store(entity, activity=honking)

    # The Activities should match
    honking2 = syn.getProvenance(entity)
    assert honking['id'] == honking2['id']


def test_store_isRestricted_flag():
    # Store a file with access requirements
    path = utils.make_bogus_binary_file()
    schedule_for_cleanup(path)
    entity = File(path, name='Secret human data', parent=project)
    
    # We don't want to spam ACT with test emails
    with patch('synapseclient.client.Synapse._createAccessRequirementIfNone') as intercepted:
        entity = syn.store(entity, isRestricted=True)
        assert intercepted.called


def test_ExternalFileHandle():
    # Tests shouldn't have external dependencies, but this is a pretty picture of Singapore
    singapore_url = 'http://upload.wikimedia.org/wikipedia/commons/thumb/3/3e/1_singapore_city_skyline_dusk_panorama_2011.jpg/1280px-1_singapore_city_skyline_dusk_panorama_2011.jpg'
    singapore = File(singapore_url, parent=project, synapseStore=False)
    singapore = syn.store(singapore)

    # Verify the file handle
    fileHandle = syn._getFileHandle(singapore.dataFileHandleId)
    assert fileHandle['concreteType'] == 'org.sagebionetworks.repo.model.file.ExternalFileHandle'
    assert fileHandle['externalURL']  == singapore_url

    # The download should occur only on the client side
    singapore = syn.get(singapore, downloadFile=True)
    assert singapore.path is not None
    assert singapore.externalURL == singapore_url
    assert os.path.exists(singapore.path)

    # Update external URL
    singapore_2_url = 'https://upload.wikimedia.org/wikipedia/commons/a/a2/Singapore_Panorama_v2.jpg'
    singapore.externalURL = singapore_2_url
    singapore = syn.store(singapore)
    s2 = syn.get(singapore, downloadFile=False)
    assert s2.externalURL == singapore_2_url


def test_copy():
    """Tests the 'synapse cp' function"""
    # Create a Project
    project_entity = syn.store(Project(name=str(uuid.uuid4())))
    schedule_for_cleanup(project_entity.id)
    acl = syn.setPermissions(project_entity, other_user['principalId'], accessType=['READ', 'CREATE', 'UPDATE'])
    # Create two Folders in Project
    folder_entity = syn.store(Folder(name=str(uuid.uuid4()),
                                                   parent=project_entity))
    second_folder = syn.store(Folder(name=str(uuid.uuid4()),
                                                   parent=project_entity))
    third_folder = syn.store(Folder(name=str(uuid.uuid4()),
                                                   parent=project_entity))
    schedule_for_cleanup(folder_entity.id)
    schedule_for_cleanup(second_folder.id)
    schedule_for_cleanup(third_folder.id)

    # Annotations and provenance
    repo_url = 'https://github.com/Sage-Bionetworks/synapsePythonClient'
    annots = {'test':['hello_world']}
    prov = Activity(name = "test",used = repo_url)
    # Create, upload, and set annotations/provenance on a file in Folder
    filename = utils.make_bogus_data_file()
    schedule_for_cleanup(filename)
    file_entity = syn.store(File(filename, parent=folder_entity))
    externalURL_entity = syn.store(File(repo_url,name='rand',parent=folder_entity,synapseStore=False))
    syn.setAnnotations(file_entity,annots)
    syn.setAnnotations(externalURL_entity,annots)
    syn.setProvenance(externalURL_entity.id, prov)
    schedule_for_cleanup(file_entity.id)
    schedule_for_cleanup(externalURL_entity.id)
    
    output = syn.copy(file_entity.id,project_entity.id)
    output_URL = syn.copy(externalURL_entity.id,project_entity.id)

    #Verify that our copied files are identical
    copied_ent = syn.get(output)
    copied_URL_ent = syn.get(output_URL,downloadFile=False)
    copied_ent_annot = syn.getAnnotations(output)
    copied_url_annot = syn.getAnnotations(output_URL)
    copied_prov = syn.getProvenance(output)
    copied_url_prov = syn.getProvenance(output_URL)
    schedule_for_cleanup(output)
    schedule_for_cleanup(output_URL)

    # TEST: set_Provenance = Traceback
    print("Test: setProvenance = Traceback")
    assert copied_prov['used'][0]['reference']['targetId'] == file_entity.id
    assert copied_url_prov['used'][0]['reference']['targetId'] == externalURL_entity.id

    # TEST: Make sure copied files are the same
    assert copied_ent_annot == annots
    assert copied_ent.dataFileHandleId == file_entity.dataFileHandleId

    # TEST: Make sure copied URLs are the same
    assert copied_url_annot == annots
    assert copied_URL_ent.externalURL == repo_url
    assert copied_URL_ent.name == 'rand'
    assert copied_URL_ent.dataFileHandleId == externalURL_entity.dataFileHandleId

    #Verify that errors are being thrown when folders/projects are attempted to be copied,
    #or file is copied to a folder/project that has a file with the same filename
    assert_raises(AttributeError,syn.copy,folder_entity.id,parentId = project_entity.id)
    assert_raises(AttributeError,syn.copy,project_entity.id,parentId = project_entity.id)
    assert_raises(ValueError,syn.copy,file_entity.id,parentId = project_entity.id) 
    assert_raises(ValueError,syn.copy,file_entity.id,parentId = third_folder.id,setProvenance = "gib")

    print("Test: setProvenance = None")
    output = syn.copy(file_entity.id,second_folder.id,setProvenance = None)
    assert_raises(SynapseHTTPError,syn.getProvenance,output)
    schedule_for_cleanup(output)

    print("Test: setProvenance = Existing")
    output_URL = syn.copy(externalURL_entity.id,second_folder.id,setProvenance = "existing")
    output_prov = syn.getProvenance(output_URL)
    schedule_for_cleanup(output_URL)
    assert output_prov['name'] == prov['name']
    assert output_prov['used'] == prov['used']

    if 'username' not in other_user or 'password' not in other_user:
        sys.stderr.write('\nWarning: no test-authentication configured. skipping testing copy function when trying to copy file made by another user.\n')
        return

    try:
        print("Test: Other user copy should result in different data file handle")
        syn_other = synapseclient.Synapse(skip_checks=True)
        syn_other.login(other_user['username'], other_user['password'])

        output = syn_other.copy(file_entity.id,third_folder.id)
        new_copied_ent = syn.get(output)
        new_copied_ent_annot = syn.getAnnotations(output)
        schedule_for_cleanup(new_copied_ent)
        
        copied_URL_ent.externalURL = "https://www.google.com"
        copied_URL_ent = syn.store(copied_URL_ent)
        output = syn_other.copy(copied_URL_ent.id,third_folder.id,version=1)
        new_copied_URL = syn.get(output,downloadFile=False)

        schedule_for_cleanup(new_copied_URL)

        assert new_copied_ent_annot == annots
        assert new_copied_ent.dataFileHandleId != copied_ent.dataFileHandleId
        #Test if copying different versions gets you the correct file
        assert new_copied_URL.versionNumber == 1
        assert new_copied_URL.externalURL == repo_url
        assert new_copied_URL.dataFileHandleId != copied_URL_ent.dataFileHandleId
    finally:
        syn_other.logout()
    #Test: Different users copying- > Data file handle will be different
    #Test: versioning


def test_synapseStore_flag():
    # Store a path to a local file
    path = utils.make_bogus_data_file()
    schedule_for_cleanup(path)
    bogus = File(path, name='Totally bogus data', parent=project, synapseStore=False)
    bogus = syn.store(bogus)
    
    # Verify the thing can be downloaded as a URL
    bogus = syn.get(bogus, downloadFile=False)
    assert bogus.name == 'Totally bogus data'
    assert bogus.path == path, "Path: %s\nExpected: %s" % (bogus.path, path)
    assert bogus.synapseStore == False

    # Make sure the test runs on Windows and other OS's
    if path[0].isalpha() and path[1]==':':
        # A Windows file URL looks like this: file:///c:/foo/bar/bat.txt
        expected_url = 'file:///' + path.replace("\\","/")
    else:
        expected_url = 'file://' + path

    assert bogus.externalURL == expected_url, 'URL: %s\nExpected %s' % (bogus.externalURL, expected_url)

    # A file path that doesn't exist should still work
    bogus = File('/path/to/local/file1.xyz', parentId=project.id, synapseStore=False)
    bogus = syn.store(bogus)
    assert_raises(IOError, syn.get, bogus)
    assert bogus.synapseStore == False

    # Try a URL
    bogus = File('http://dev-versions.synapse.sagebase.org/synapsePythonClient', parent=project, synapseStore=False)
    bogus = syn.store(bogus)
    bogus = syn.get(bogus)
    assert bogus.synapseStore == False


def test_create_or_update_project():
    name = str(uuid.uuid4())

    project = Project(name, a=1, b=2)
    syn.store(project)

    project = Project(name, b=3, c=4)
    project = syn.store(project)

    assert project.a == [1]
    assert project.b == [3]
    assert project.c == [4]

    project = syn.get(project.id)

    assert project.a == [1]
    assert project.b == [3]
    assert project.c == [4]

    project = Project(name, c=5, d=6)
    try:
        project = syn.store(project, createOrUpdate=False)
        assert False, "Expect an exception from storing an existing project with createOrUpdate=False"
    except Exception as ex1:
        pass


def test_download_file_false():
    RENAME_SUFFIX = 'blah'
    
    # Upload a file
    filepath = utils.make_bogus_binary_file()
    schedule_for_cleanup(filepath)
    schedule_for_cleanup(filepath + RENAME_SUFFIX)
    file = File(filepath, name='SYNR 619', parent=project)
    file = syn.store(file)
    
    # Now hide the file from the cache and download with downloadFile=False
    os.rename(filepath, filepath + RENAME_SUFFIX)
    file = syn.get(file.id, downloadFile=False)
    
    # Change something and reupload the file's metadata
    file.name = "Only change the name, not the file"
    reupload = syn.store(file)
    assert reupload.path is None, "Path field should be null: %s" % reupload.path
    
    # This should still get the correct file
    reupload = syn.get(reupload.id)
    assert filecmp.cmp(filepath + RENAME_SUFFIX, reupload.path)
    assert reupload.name == file.name

def test_download_file_URL_false():
    # Upload an external file handle
    fileThatExists = 'http://dev-versions.synapse.sagebase.org/synapsePythonClient'
    reupload = File(fileThatExists, synapseStore=False, parent=project)
    reupload = syn.store(reupload)
    reupload = syn.get(reupload, downloadFile=False)
    originalVersion = reupload.versionNumber
    
    # Reupload and check that the URL and version does not get mangled
    reupload = syn.store(reupload, forceVersion=False)
    assert reupload.path == fileThatExists, "Entity should still be pointing at a URL"
    assert originalVersion == reupload.versionNumber

    # Try a URL with an extra slash at the end
    fileThatDoesntExist = 'http://dev-versions.synapse.sagebase.org/synapsePythonClient/'
    reupload.synapseStore = False
    reupload.path = fileThatDoesntExist
    reupload = syn.store(reupload)
    reupload = syn.get(reupload, downloadFile=False)
    originalVersion = reupload.versionNumber
    
    reupload = syn.store(reupload, forceVersion=False)
    assert reupload.path == fileThatDoesntExist, "Entity should still be pointing at a URL"
    assert originalVersion == reupload.versionNumber

