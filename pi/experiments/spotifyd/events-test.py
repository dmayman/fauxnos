#!/usr/bin/env python3
import asyncio
from dbus_next.aio import MessageBus
from dbus_next import Message
from dbus_next.constants import BusType

async def find_spotifyd_name(bus):
    # Call ListNames on the bus daemon
    msg = Message(
        destination='org.freedesktop.DBus',
        path='/org/freedesktop/DBus',
        interface='org.freedesktop.DBus',
        member='ListNames'
    )
    reply = await bus.call(msg)
    names = reply.body[0]  # a list of all well-known names
    for name in names:
        print(name)
        if name.startswith('org.mpris.MediaPlayer2.spotifyd'):
            return name
    raise RuntimeError("spotifyd MPRIS bus name not found")

async def main():
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

    mpris_name = await find_spotifyd_name(bus)
    print(f"Found spotifyd on D-Bus as: {mpris_name}")

    introspection = await bus.introspect(
        mpris_name,
        '/org/mpris/MediaPlayer2'
    )
    proxy = bus.get_proxy_object(mpris_name, '/org/mpris/MediaPlayer2', introspection)
    props = proxy.get_interface('org.freedesktop.DBus.Properties')

    def on_props_changed(interface, changed, invalidated):
        print(f"DBUS Event - Interface: {interface}")
        for prop, value in changed.items():
            if prop == 'PlaybackStatus':
                print(f"  ▶️ PlaybackStatus: {value.value}")
            elif prop == 'Volume':
                print(f"  🔊 Volume: {value.value:.0%}")
            elif prop == 'Metadata':
                metadata = value.value
                if 'xesam:title' in metadata:
                    print(f"  🎵 Title: {metadata['xesam:title'].value}")
                if 'xesam:artist' in metadata:
                    artists = metadata['xesam:artist'].value
                    print(f"  👤 Artist: {', '.join(artists)}")
                if 'xesam:album' in metadata:
                    print(f"  💿 Album: {metadata['xesam:album'].value}")
            else:
                print(f"  📋 {prop}: {value.value}")
        
        if invalidated:
            print(f"  ❌ Invalidated properties: {invalidated}")

    props.on_properties_changed(on_props_changed)

    print("Listening for events…")
    await asyncio.Future()  # run forever

if __name__ == '__main__':
    asyncio.run(main())