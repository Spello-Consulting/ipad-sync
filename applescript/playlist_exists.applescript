-- Report whether a playlist exists in the macOS TV app.
-- Usage: osascript playlist_exists.applescript "<playlist name>"
-- Prints "1" if the playlist exists, "0" otherwise.
on run argv
	set playlistName to item 1 of argv
	tell application "TV"
		if exists playlist playlistName then
			return "1"
		else
			return "0"
		end if
	end tell
end run
