#!/usr/bin/env python3
"""
Fixture capture script for Music Assistant client.

This script runs the comprehensive test sequence using the DebugMusicAssistantClient
to capture all real Music Assistant API responses as JSON fixtures for unit testing.
"""

import os
import sys
import time
import traceback
from typing import cast

from music_assistant_models.enums import MediaType
from ovos_bus_client import MessageBusClient
from ovos_utils.fakebus import FakeBus

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from skill_musicassistant import MusicAssistantSkill
from skill_musicassistant.debug_client import DebugMusicAssistantClient


def run_fixture_capture():
    """Run the test sequence with debug client for fixture capture."""
    print("🎵 Starting kid-friendly Music Assistant fixture capture...")

    # Create skill with debug client
    skill = MusicAssistantSkill(bus=cast(MessageBusClient, FakeBus()), skill_id="skill-musicassistant-fixture-capture")

    # Replace the normal client with debug client
    skill.session = skill.session  # Keep the session
    skill.mass_client = DebugMusicAssistantClient(
        server_url=skill.music_assistant_url, session=skill.session, fixture_capture=True, fixture_dir="test/fixtures"
    )

    try:
        print("\n2️⃣ Testing player discovery...")
        players = skill.mass_client.get_players()
        print(f"✅ Found {len(players)} players:")
        for player in players:
            print(f"   - {player.name} (ID: {player.player_id})")

        # Use the reliable Chromecast Office speaker
        office_player = skill._get_player_id("Office Speaker")
        if not office_player:
            print("❌ Could not find Office Speaker, using first available player")
            if players:
                office_player = players[0].player_id
                print(f"✅ Using player: {players[0].name}")
            else:
                print("❌ No players available, cannot continue test")
                return
        else:
            print(f"✅ Found Office speaker: {office_player}")

        print("\n3️⃣ Testing search functionality...")
        # Test artist search
        artist = skill._search_media("Carbon Leaf", MediaType.ARTIST)
        if artist:
            print(f"✅ Found artist: {artist.name}")
        else:
            print("❌ Artist search failed")

        # Test track search
        track = skill._search_media("Life Less Ordinary", MediaType.TRACK, artist="Carbon Leaf")
        if track:
            print(f"✅ Found track: {track.name}")
        else:
            print("⚠️ Track search failed (might not be available)")

        print("\n4️⃣ Testing playback and state capture...")
        if artist:
            success = skill._play_media_item(artist, office_player, radio_mode=False)
            if success:
                print("✅ Successfully started Carbon Leaf playback!")
                time.sleep(2)  # Let it play briefly
            else:
                print("❌ Failed to start playback")

        print("\n5️⃣ Testing playback controls with state validation...")
        # Capture initial state
        skill.mass_client.show_current_state(office_player, "After playback start")
        time.sleep(1)

        # Test pause
        print("   ⏸️ Testing PAUSE command...")
        skill.mass_client.queue_command_pause(office_player)
        time.sleep(1)
        skill.mass_client.show_current_state(office_player, "After pause")

        # Test play/resume
        print("   ▶️ Testing PLAY/RESUME command...")
        skill.mass_client.queue_command_play(office_player)
        time.sleep(1)
        skill.mass_client.show_current_state(office_player, "After resume")

        # Test next track
        print("   ⏭️ Testing NEXT TRACK command...")
        skill.mass_client.queue_command_next(office_player)
        time.sleep(2)
        skill.mass_client.show_current_state(office_player, "After next track")

        # Test previous track
        print("   ⏮️ Testing PREVIOUS TRACK command...")
        skill.mass_client.queue_command_previous(office_player)
        time.sleep(2)
        skill.mass_client.show_current_state(office_player, "After previous track")

        print("\n6️⃣ Testing volume controls (kid-safe limits)...")
        # Test volume down
        skill.mass_client.player_command_volume_down(office_player, step=5)
        time.sleep(1)
        skill.mass_client.show_current_state(office_player, "After volume down")

        # Test volume up
        skill.mass_client.player_command_volume_up(office_player, step=3)
        time.sleep(1)
        skill.mass_client.show_current_state(office_player, "After volume up")

        # Test set volume
        skill.mass_client.player_command_volume_set(office_player, volume=25)
        time.sleep(1)
        skill.mass_client.show_current_state(office_player, "After set volume 25%")

        print("\n7️⃣ Testing different media types...")
        album = skill._search_media("Echo Echo", MediaType.ALBUM, artist="Carbon Leaf")
        if album:
            print(f"✅ Found album: {album.name}")
            success = skill._play_media_item(album, office_player, radio_mode=False)
            if success:
                print("✅ Album playback started!")
                time.sleep(2)

        print("\n8️⃣ Final cleanup...")
        skill.mass_client.queue_command_pause(office_player)
        time.sleep(1)
        skill.mass_client.show_current_state(office_player, "Final pause")

        # Show fixture stats
        stats = skill.mass_client.get_fixture_stats()
        print("\n📊 Fixture capture statistics:")
        print(f"   🗂️ Directory: {stats['fixture_dir']}")
        print(f"   📄 Files captured: {stats['fixture_count']}")
        print(f"   🔢 Latest counter: {stats['latest_counter']}")

    except Exception as e:
        print(f"❌ Error during fixture capture: {e}")
        traceback.print_exc()
        raise
    finally:
        if skill.session:
            skill.session.close()
            print("✅ Session cleaned up")


if __name__ == "__main__":
    print("🎯 Starting fixture capture with DebugMusicAssistantClient...")
    print("📁 Fixtures will be saved to test/fixtures/")
    print("🎵 Running comprehensive Music Assistant test sequence...")
    print()

    try:
        run_fixture_capture()
        print()
        print("✅ Fixture capture completed!")
        print("📁 Check test/fixtures/ for captured JSON files")
        print("🧪 Ready to write unit tests using these fixtures")
        print("🔧 Users can now use DebugMusicAssistantClient for troubleshooting!")
    except Exception as e:
        print(f"❌ Fixture capture failed: {e}")
        traceback.print_exc()
        sys.exit(1)
