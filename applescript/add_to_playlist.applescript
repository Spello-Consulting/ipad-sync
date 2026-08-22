-- Add tracks (by POSIX file path) to a playlist in the macOS TV app.
-- Usage: osascript add_to_playlist.applescript "<playlist name>" "<paths file>"
--
-- <paths file> is a UTF-8 text file of POSIX media paths, one per line. The
-- playlist is created if it does not exist. Files already in the TV library are
-- added to the playlist by reference; files not yet in the library are imported.
-- Prints the number of tracks added.
on run argv
	set playlistName to item 1 of argv
	set listFile to item 2 of argv
	set fileText to (read (POSIX file listFile) as «class utf8»)
	set AppleScript's text item delimiters to linefeed
	set thePaths to text items of fileText
	set AppleScript's text item delimiters to ""
	set addedCount to 0
	tell application "TV"
		if not (exists playlist playlistName) then
			make new playlist with properties {name:playlistName}
		end if
		set thePlaylist to playlist playlistName
		with timeout of 3600 seconds
			repeat with p in thePaths
				set pStr to (p as text)
				if pStr is not "" then
					try
						add (POSIX file pStr) to thePlaylist
						set addedCount to addedCount + 1
					end try
				end if
			end repeat
		end timeout
	end tell
	return (addedCount as text)
end run
