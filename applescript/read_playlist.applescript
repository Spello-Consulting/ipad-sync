-- Bulk-read a playlist's file tracks from the macOS TV app.
-- Usage: osascript read_playlist.applescript "<playlist name>"
--
-- Prints three blobs separated by ASCII 29 (group separator):
--   <names> <GS> <locations> <GS> <shows>
-- Within each blob, entries are separated by ASCII 30 (record separator).
-- Locations are raw HFS paths (e.g. "Data_IT:Multimedia:Video:Movie.m4v");
-- conversion to POSIX and all matching is done in Python. `show` is the TV
-- series name (empty / "missing value" for movies).
--
-- Only `file track`s are read, so streamed/URL tracks (which have no local
-- location) are skipped rather than causing an all-or-nothing failure.
-- Returns an empty string if the playlist does not exist.
on run argv
	set playlistName to item 1 of argv
	set recordSep to (ASCII character 30)
	set groupSep to (ASCII character 29)
	tell application "TV"
		if not (exists playlist playlistName) then
			return ""
		end if
		set thePlaylist to playlist playlistName
		-- Raise the Apple event timeout: the bulk property fetch can exceed the
		-- default 120s on large playlists (error -1712).
		with timeout of 3600 seconds
			set trackNames to name of every file track of thePlaylist
			set trackLocations to location of every file track of thePlaylist
			set trackShows to show of every file track of thePlaylist
		end timeout
	end tell
	set AppleScript's text item delimiters to recordSep
	set nameBlob to trackNames as text
	set locBlob to trackLocations as text
	set showBlob to trackShows as text
	set AppleScript's text item delimiters to ""
	return nameBlob & groupSep & locBlob & groupSep & showBlob
end run
