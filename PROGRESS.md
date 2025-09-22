8/12/2025
- Spotify broke the api so librespot, spotifyd, go-librespot all aren't working
- go-librespot has a fix but am waiting on them to include it in a release so i dont have to build it from source https://github.com/devgianlu/go-librespot/releases/tag/v0.3.2
-   


9/20/2025
- Fully changed course because most other paths just don't work.
- Now using go-librespot and snapcast exclusively. For every client, there is a server-side go-librespot instance and snapcast fifo stream.
- On snapserver, there's one group per client, and each group defaults to the designated fifo stream. Example:
    - go-librespot instance "FauxnosGo_Stream1" is set to pipe to "spotifystream1" fifo.
    - snapserver source "Spotify1" uses "spotifystream1" fifo.
    - snapclient "fauxnos1" is added to group 0 that defaults to "Spotify1" source, but that can be changed. I think I'd only ever change the source of a group to either the default, or Analog In (need to explore this next).
    - Obviously need to rename all of these
- In Spotify, all go-librespot instances are visible. Snapclients just tune into them through the group they are in.
- To achieve multi-room, snapclients' can be moved to different groups. So you'd move fauxnos1 to fauxnos2's group, both would get Spotify2.
    - UX would be: Start playing to a room, add another room to that room. As long as we keep track of which group defaults to which client, the app can visualize this easily
- Volume control for each client is possible. Go-librespot announces the volume set by the Spotify app, but does not change any volume. /experiments/snapcast/vollisten.py is a proof of concept that shows we can listen to go-librespot's volume events and change snapclient volumes.
- We can use the existing algo in snapcast_controller.py to control group volumes by sending a volume event to each client in the group.

NEXT UP: 
- Pulseaudio is still required for Analog In because it needs to be as fast as possible. We'll use the same config, but we only need two PA sources (snapcast and analog in).
