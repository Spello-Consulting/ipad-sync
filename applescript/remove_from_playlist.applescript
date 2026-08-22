-- Remove tracks (by HFS location) from a playlist in the macOS TV app.
-- Usage: osascript remove_from_playlist.applescript "<playlist name>" "<locs file>"
--
-- <locs file> is a UTF-8 text file of HFS location strings (e.g.
-- "Data_IT:Multimedia:Video:Movie.m4v"), one per line — matched against each
-- track's stored location without resolving the file, so tracks whose media is
-- missing can still be removed. `delete` removes the track from this playlist
-- only, not from the library. Prints the number of tracks removed.
on run argv
	set playlistName to item 1 of argv
	set listFile to item 2 of argv
	set fileText to (read (POSIX file listFile) as «class utf8»)
	set AppleScript's text item delimiters to linefeed
	set targetLocs to text items of fileText
	set AppleScript's text item delimiters to ""
	set removedCount to 0
	tell application "TV"
		if not (exists playlist playlistName) then
			return "0"
		end if
		set thePlaylist to playlist playlistName
		with timeout of 3600 seconds
			-- Iterate backwards so deletions do not shift the indexes still to visit.
			repeat with i from (count of file tracks of thePlaylist) to 1 by -1
				set t to file track i of thePlaylist
				set loc to ((location of t) as text)
				if targetLocs contains loc then
					delete t
					set removedCount to removedCount + 1
				end if
			end repeat
		end timeout
	end tell
	return (removedCount as text)
end run
