# iPad Sync Requirements

## Objective

An application that allows me to synchronise the media listed in an Apple TV playlist with a specified media player app (initially Infuse) on my iPad. 

This app can do two primary operations:

1. Update the Infuse app's Documents contents so that it mirrors the media listed in the Apple TV playlist.
2. Rebuild the Apple YT platlist based on the documents currently present in the Infuse app's storage. 

This two way mirroring feature is important because I have multiple macOS machines that may be a source of the iPad synchronisation. Each macOS system will have its own local copy of the TV and Movie files, although the full path to the media on these systems may be differ. 

## Example Workflow 

Here's a typical workflow:

1. On MacMiniAU (my Sydney desktop), my media lives at `/Volumes/Data_AU/Multimedia/Video`. All the files and folders under here are imported into Apple TV
2. On Apple TV on MacMiniAU I build a playlist called `iPad Sync`, selecting multiple movies and TV shows.
3. I use this ipad-sync app to copy the media listed in this playlist to the Infuse Documents storage on my iPad. 
    1. Any files present on the iPad but not in the playlist are removed.
    2. Relative paths are preserved. For example if my playlist included this TV show: `/Volumes/Data_IT/Multimedia/Video/Star Trek/Season 2/Star Trek-S02E01-Amok Time.m4v` then the file would be created under Infuse Documents as `Star Trek/Season 2/Star Trek-S02E01-Amok Time.m4v`
4. I now travel to Spello and fire up my MacMiniIT macOS desktop. It has all its media files under `/Volumes/Data_IT/Multimedia/Video` (Data_IT is a clone of Data_AU) and all are imported in the Apple TV app on that machine.
5. I use this ipad-sync app to rebuild the `iPad Sync` Apple TV playlist on MacMiniIT using the contents of the Infuse Documents storage on my iPad.
    1. ipad-sync compares the iPad files with the relative path from to the media root on the MacMiniIT
    2. If the iPad file also exists on the macOS desktop (eg. `Star Trek/Season 2/Star Trek-S02E01-Amok Time.m4v` in Infuse Documents is matched to `/Volumes/Data_IT/Multimedia/Video/Star Trek/Season 2/Star Trek-S02E01-Amok Time.m4v` when the playlist entry is added using the full path `/Volumes/Data_IT/Multimedia/Video/Star Trek/Season 2/Star Trek-S02E01-Amok Time.m4v`)
    3. If the iPad file doesn't exist on the macOS desktop, the playlist entry is not created. 
    4. For speed, the Apple TV playlist can simply be deleted and then rebuilt as per the points above, rather than incrementally editied. 

## Additional Context

This design document is based on this  prior [Claude chat](https://claude.ai/share/3a4b25a8-c10d-4e38-8f62-d034faad6c3d). This chat has been summarised in the `docs/apple-tv-infuse-sync-notes.md` document. 

## Application Details

A shell application has been created at ~/dev/ipad-sync, including

- Development configuration file has been created
- pymobiledevice3 package imported using uv
- Log activity using the SCLogger object

## Application Startup

When the ipad-sync starts it must perform the follwing checks first, regardless of the operation requested on the command line.

1. Confirm the iPad is connected via USB (`pymobiledevice3 usbmux list`)
2. Confirm that there is a trust relationship between the desktop running ipad-sync and the ipad (`pymobiledevice3 lockdown pair`)
3. Confirm that the media folder (AppleTV.MediaFolder config option) exists and is accessible. 
4. Checks to see if the Apple TV playlist already exists (it's OK if it doesn't). If it exists, make sure it's accessible
5. Lookup the Bundle ID for the iPad app name specified in the iPad.AppName config option. This could be done using the  `pymobiledevice3 apps list` command to do this. ipad-sync would need to extract the Bundle ID key and CFBundleDisplayName key value from the command's output for each app. This data should be saved for all apps so thatit's avalable to the List iPad Apps command (see below.)

Sample partial output from `pymobiledevice3 apps list`
```
    "com.firecore.infuse": {
        "AdaptyAppleSearchAdsAttributionCollectionEnabled": true,
        "ApplicationDSID": 273615271,
        "ApplicationType": "User",
        "BGTaskSchedulerPermittedIdentifiers": [
            "com.firecore.infuse.bg_services",
            "com.firecore.infuse.download_continued"
        ],
        "BuildMachineOSBuild": "25E246",
        "CADisableMinimumFrameDurationOnPhone": true,
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": "Infuse",
        "CFBundleDocumentTypes": [
            ...
```

These startup checks may cause various approval dialogs to pop-up on the iPad and/or Mac. This give us a change to approve all of these before we start any operation.

## Operations 

The ipad-sync app will support the following operations. Each one is invoked via a command line argument. The app will carry out this operation, log the progress to the log file and/or console (as per the Files: configuration section) and then exit.

The following operations will be supported:

### List iPad Apps (cmd: ipad-apps)

This lists all the apps installed on the iPad and then Display Name (CFBundleDisplayName) and Bundle ID for each one. This data is build as part the application startup routinue (see above)

This operation data can be used for manual testing with pymobiledevice3

### List Playlist (cmd: list-playlist)

List the contents of the Apple TV playlist as specified in the AppleTV.Playlist config option. For each Track, list the Name and media path converted into POSIX format

To so this, ipad-sync will need to shell out to an AppleScript script to get the playlist contents - see `applescript-samples/ListPlaylist.scpt` for a simple example. 

It's recommanded that the conversion of the track's raw location text (e.g. "Data_IT:Multimedia:Video:Fire in the Sky [1993].m4v") into the proper POSIX path (`/Volumes/Data_IT/Multimedia/Video/Fire in the Sky [1993].m4v`) be done in Python code rather than the Apple Script. 

For each track, once we have the POSIX path, do a file system check to make sure the file exists and get the file size. If the file doesn't exist, exclude it from the Playlist data object list.

Code code for this operation can also be used by more complex operations (e.g. to-ipad), the first step of which would be to get a listing of of the playlist.

### List iPad (cmd: list-ipad)

List the contents of of the iPad Infuse app's Documents. Show each file with the relative path and file size. 

### Compare (cmd: compare)

Thsi uses the `list-playlist` and  `list-ipad` operation data objects to calculate which files need to be copied to the iPad and which would be removed from it.

### Mirror to iPad (cmd: to-ipad)

This command will copy the media files from the ApleTV.MediaFolder to the Infuse app's Documents folder as per the contents of the playlist.

- If the Apple TV playlist is empty, abort with an error. 
- First do a `list-ipad` operation to get a data object showing which files need to be copied over and which need to be removed from the iPad. After listing the proposed changes, ask for confirmation before proceeding. 
- If possible, calculate the total change in storage requirements on the iPad and confirm that it'll all fit after all delete and add operations are complete (use the `pymobiledevice3 apps afc` info command to get total free space.) Do not let the iPad storage drop below the iPad.MinimumFreeSpaceGB value (defaults to 1 Gb)
- Show real progress as the copy rogreses, taking into account file sizes and projected total copy time.
- Any files present on the iPad storage but not in the playlist are removed. 
- Do delete operations before copy operations.
- Relative paths are preserved. For example if my playlist included this TV show: `/Volumes/Data_IT/Multimedia/Video/Star Trek/Season 2/Star Trek-S02E01-Amok Time.m4v` then the file would be created under Infuse Documents as `Star Trek/Season 2/Star Trek-S02E01-Amok Time.m4v`

### Update Playlist (cmd: to-playlist)




# More

Preserve folder structure when copying, relative to AppleTV.MediaFolder

Match iPad files by relative path to /Documents root:

```
Ad Astra [2019].m4v
'Star Trek/Season 2/Star Trek-S02E01-Amok Time.m4v'
```

Initially this will be Infuse, but the app is designed to support other iPad OS apps in the future 

Phased implementation