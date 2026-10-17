# Changelog

## [1.0.1](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v1.0.0...v1.0.1) (2026-10-17)


### Bug Fixes

* allow ovos-bus-client 2.x and ovos-workshop up to 9.x ([5370acf](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/5370acf978642e086a4f86085863510cb08c61a8))
* allow ovos-bus-client 2.x and ovos-workshop up to 9.x ([24029be](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/24029bedfd291389f86a2ce7ce746822142e945f))
* an artist, album, playlist or station replaces the queue ([2120a8e](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/2120a8e1a35337642934c0377c1b5abd0873bd37))
* an artist, album, playlist or station replaces the queue ([e9abde5](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/e9abde5da358854d3a2902c8fab7c7963a9d4d88))
* require ma-http-client 0.2.1 and re-record the random scenarios ([67d51d5](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/67d51d5ba6f853b5c600769e7a04c25b33ee0a43))

## [1.0.0](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v0.4.4...v1.0.0) (2026-10-17)


### ⚠ BREAKING CHANGES

* the play_artist, play_album, play_track, play_playlist, play_radio, play_genre, play_random and play_radio_category intents are gone; every phrasing they accepted is handled by play.intent. The generic_play_fallback setting and all other settings keep their meaning.
* the 1.0 line changes how requests are resolved. The skill now depends on the ma-http-client package (0.2.0 or later) instead of a vendored client; a generic "play X" fallback handler is on by default (setting generic_play_fallback); track and album requests are resolved by name on the server and the skill tells you when it matched a different artist; "stop" pauses the session's last player instead of the first player on the server; new now-playing and like intents exist. Upgrade at your own risk; review your intents and settings after upgrading.

### Features

* create, fill, trim, save, and list playlists by voice ([9f32262](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/9f32262d00964fb07dba0b23452b914916a525cc))
* depend on ma-http-client instead of a vendored client copy ([493f6f9](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/493f6f939800ccd499c4c5880b01697417fe41a3))
* depend on ma-http-client instead of a vendored client copy ([afcc296](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/afcc296d48e7768e7ddafda073208b01e5e5a6df))
* one play intent, one play pipeline, one feedback policy ([ede8218](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/ede82187acd24e2d8c7964c60f295d8388aeb731))
* **parser:** add deterministic MediaRequest parser with grammar table tests ([ac3f29e](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/ac3f29ede071b695371a93a7dd7bb2cfb9739312))
* play by genre, random library mixes, and shuffle/repeat by voice ([2bbe3a1](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/2bbe3a14b19289f10cd910625da48e535e596f38))
* play radio by country, language, or genre tag ([7d3e995](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/7d3e995f49ea8332285df6c161576663228b01f5))
* resolve bare "play X", say what matched, add now-playing and like ([cff457f](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/cff457f0a88944bb3efc244e741534f5982cdd58))
* **resolve:** resolve MediaRequests with contract tests on recorded responses ([78a4c09](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/78a4c09b7dc52a859fa0055781b3a00f18e39f49))


### Bug Fixes

* an idle player is "nothing playing", whatever its leftover media says ([e7db13b](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/e7db13bfb620f8cffd9c0fe7b15fa8b2ad8879cb))
* collapse location variants in volume, pause, next and previous intents ([6ec3eef](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/6ec3eef2e8e5ae33d3a901e2827c4b2f1c3b1ae6))
* find short station names by also searching with "radio" inserted ([5ae33d9](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/5ae33d90a5fcee0b1d749c52b886ce6454b56ea2))
* genre names must match as a whole ([52e3ec9](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/52e3ec9d783d1764c9b1f6d8a0d27e77d6eef2c0))
* hear "tune in to", and rank radio stations by their real names ([7132501](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/7132501d854788c3cff08a7774a934dfae9fe924))
* match "play X playlist" with the name before the keyword ([0c8b40b](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/0c8b40b079d47b16a577fb0b10dea03e5df34d41))
* match whole names when resolving bare requests, and play another artist's version ([8bfdb66](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/8bfdb66a8a539e0b5abc9d972849dbfb8a5f46e1))
* name the station when a stream is playing, and search radio by the spoken name ([a389d3a](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/a389d3a48b736fe79160773f1431491a8c3ea430))
* pick genres by name, fall back to albums, and treat non-genres as "play X" ([d81594b](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/d81594bad828110e645b67f3d1fc60f997b0f083))
* prefer the exact player name when fuzzy scores tie ([ef04bbf](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/ef04bbf7bc6fb8855d304f7c1d88f6d450827b1c))
* radio discovery replaces the queue and queues five stations ([9b96e0a](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/9b96e0a4a5e16d86d26b7501a9ee90bf065a9544))
* **radio:** try the next station when the first one fails to start ([d765bbc](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/d765bbcd46555f850a2ba8450d6c074b1339b9e1))
* rank bare "play X" by artist, album, then track, and hear "right now" ([302282a](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/302282aeced1c4f5b2eb8e2769a1acb4a199bf0a))
* real stop, pause and resume; survive a bad settings file; persist settings atomically ([e043184](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/e043184a4360a2a00e1c8039c71ec9fbe67157bd))
* replace the queue for genre and random plays, and cap album fallback ([7dbf6ab](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/7dbf6abe4950d81bcadc23f72dee07d746805121))
* restore the rapidfuzz import the playlist matcher needs ([d3ed6a3](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/d3ed6a34e9a28f5fa4da292322e1d1579b387d60))
* send commands without a location to the player this session last used ([3ad0294](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/3ad0294fc791a68542eeecb6a1d674a2ef8256f4))
* skip folder entries when collecting radio stations ([1446b28](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/1446b2880066a77abf26b81cba7037c9ef4b5332))
* speak every failure as what it is; never swallow an exception ([aa616e3](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/aa616e3e285acaeac5c251fe683e3d921e7d9403))
* speak something sensible when the current stream has no title ([98e2306](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/98e23060c0cc6b13687ee35546f4dba9b3180cd5))
* start the first radio station before queueing the rest ([2adee9b](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/2adee9b617723918040bf1ca05321eeda3facd1f))


### Documentation

* add the minimy-ideas feature plan ([d14d088](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/d14d088b4adfad0eab5db261e6653bb07936ba2a))
* add v2 design for parser-centric request handling ([4a05670](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/4a056704137bb8e7595987f8b0058eb1a67a40d9))
* **v2:** note the OCP classifier and Jarbas music-query datasets ([247e60b](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/247e60b0156ec63363f3a4d0210f441260f60ef3))
* **v2:** record the GLiNER benchmark and drop entity extraction ([01a1578](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/01a1578880ab95aaf74c74ca18487b1fe8f29d5e))

## [0.4.4](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v0.4.3...v0.4.4) (2026-10-16)


### Bug Fixes

* **deps:** bump urllib3 to 2.8.0 ([ebc2882](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/ebc2882f20089517f095bdf04df3dbbca5579b97))
* **deps:** bump urllib3 to 2.8.0 ([ca7a7b7](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/ca7a7b76c547f0ba542f6078a6d34d8755d6073d))

## [0.4.3](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v0.4.2...v0.4.3) (2026-09-06)


### Bug Fixes

* **deps:** bump pytest and Pygments to clear Dependabot alerts ([2633464](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/26334647fb15ce5ec992401730c94bf6eebe45c4))
* **deps:** bump pytest and Pygments to clear Dependabot alerts ([bbd7caa](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/bbd7caacda39e0851a7652ff71d20a4c5391f1a4))

## [0.4.2](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v0.4.1...v0.4.2) (2026-08-19)


### Bug Fixes

* bump urllib3, orjson, requests, filelock, idna for Dependabot alerts ([5b16ba5](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/5b16ba541abf87b4fe5e3f66bf895965aaf6f512))
* bump urllib3, orjson, requests, filelock, idna for Dependabot alerts ([cfbecb3](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/cfbecb331ccb36aa07a42bbbc579fda290fa9503))

## [0.4.1](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v0.4.0...v0.4.1) (2026-07-21)


### Bug Fixes

* prune Padatious intent expansion from 4,232 to 520 samples ([a021a55](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/a021a552d45c028ba388cb292548788605907f45))
* prune Padatious intent expansion from 4,232 to 520 samples ([c80828c](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/c80828c4ddb2186c3a107c962d664fa2c959ad56)), closes [#30](https://github.com/OscillateLabsLLC/skill-musicassistant/issues/30)

## [0.4.0](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v0.3.1...v0.4.0) (2026-07-21)


### Features

* voice-settable default player with fuzzy matching and per-session defaults ([2e7fa47](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/2e7fa475724b9124e409982d240beba67f02fc3f))
* voice-settable default player, fuzzy matching, per-session defaults, localized failure dialogs ([83f9684](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/83f968478b97efe4eb01202a2e2c1ca351ff0841))


### Bug Fixes

* drop "set" phrasings from default player intent ([b323af1](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/b323af18cada768777977e2b43a7a21b14c4c9eb))


### Documentation

* document features, voice commands, and default player behavior ([68cdc76](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/68cdc7691b0bbec8ffae218544093579c759ed8d)), closes [#12](https://github.com/OscillateLabsLLC/skill-musicassistant/issues/12)

## [0.3.1](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v0.3.0...v0.3.1) (2026-05-29)


### Bug Fixes

* remove unused play_artist.dialog ([9fe5549](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/9fe5549c3e8b32d7f3739848f26990572526ade4))
* remove unused play_artist.dialog ([4cc9656](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/4cc96567064059933cfae39084a74ca8d42b32bf)), closes [#23](https://github.com/OscillateLabsLLC/skill-musicassistant/issues/23)

## [0.3.0](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v0.2.2...v0.3.0) (2026-05-04)


### Features

* add fr-fr locale ([961beba](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/961bebac27468c303bb4b3deb7d52911b0da0d0e))
* add locale resources for volume parsing ([27f554c](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/27f554c6e44aae9d2bf444769dca3b1bf01ef577))
* localize volume parsing ([783829e](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/783829ed301992c8521f9ec136c139079d32a297))

## [0.2.2](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v0.2.1...v0.2.2) (2026-03-17)


### Documentation

* remove personal contact from README, add CONTRIBUTING.md ([dd9169a](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/dd9169a89552c9f642631ba902303729e9e93194))

## [0.2.1](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v0.2.0...v0.2.1) (2025-12-21)


### Bug Fixes

* music assistant token support ([d720b48](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/d720b48bbbf8e3732326618e51466f683a569572))
* music assistant token support ([b596c34](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/b596c3438a87ff76e0315ad59d7f12a04caeb708))

## [0.2.0](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v0.1.1...v0.2.0) (2025-09-10)


### Features

* more endpoints ([5d29c86](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/5d29c86d461adc47bfa571374a6d69b5b0840194))
* more endpoints ([1f78d4c](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/1f78d4cd80b2b5a7a50082ab2377109a8ab5a718))

## [0.1.1](https://github.com/OscillateLabsLLC/skill-musicassistant/compare/v0.1.0...v0.1.1) (2025-08-31)


### Bug Fixes

* pypi friendly dependencies ([7fdd824](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/7fdd824652fc67742d74c348e840740bd7024cd9))

## 0.1.0 (2025-08-31)


### Features

* backport support for python 3.10 ([d14e296](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/d14e29629c302abc860b8d7745efe81e8d7ce5ee))
* backport support for python 3.10 ([1164eb4](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/1164eb4c3f3cd5f8bbfe05d59b2f5340ab4a9f3c))
* improve player lookup ([49c240a](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/49c240acf2f663376e0346b12f3a4fd695bf893f))
* initial commit ([aeaea8a](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/aeaea8adad5ab95f2cb26838904f3492e5d428da))
* initial pypi release ([a4144ff](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/a4144ff9842e127b39ffa3e291839c5cc7baa398))
* remove upstream dependency ([1eab4ae](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/1eab4ae1bbf92723f9d6d8239999c77e91a9b8ed))
* volume up/down ([bcf7af0](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/bcf7af0b711830ecdd81c8f768429d31d4df8b84))


### Bug Fixes

* dict not class ([5e967eb](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/5e967eb3e87bb727efbfa106e20fdf505fb2a3bb))
* don't name the log ([b330c9e](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/b330c9e975042deb4e5b97ec7c29f51bf1b95b80))
* entrypoint ([715b83f](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/715b83fe37a7a8a2dfdd66374f3c34588f5214e1))
* handle muting better ([1461464](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/1461464cc45af4db039a7f520988149d74c7c516))
* include locale files ([5ea4ade](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/5ea4ade0d37e42a9494750c813bfe1242d97b9d3))
* music-assistant-models pip compatible source ([980b5f6](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/980b5f6e37fa720b63619b30ace554770f5e6256))
* **package:** agnostic vcs package ([645c0d0](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/645c0d0d3ed496b0b424b3125c9d6981bcefbf06))
* pause dialog ([afded7e](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/afded7e37b4d3e3a27796f4a5b02bb8d3226df4f))
* player handling ([5721078](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/572107894b5c287ebafa133ef48026c82b2ea16d))
* proper intent data ([f0fc30d](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/f0fc30d65e9fc4dbf1634a46e0a52f465c9a5558))
* proper variable for artist playback ([f91ac70](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/f91ac7073758e18d5f468018a64e0df7b52ba5c7))
* skill plugin entrypoint ([c551bed](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/c551bed2af0116b89ec5ff10bbddcd15cf7eb903))
* skill.json automation ([8504974](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/8504974f25777ba500e502993c2b938348944fd6))
* trim intents ([1461464](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/1461464cc45af4db039a7f520988149d74c7c516))
* volume level ([afded7e](https://github.com/OscillateLabsLLC/skill-musicassistant/commit/afded7e37b4d3e3a27796f4a5b02bb8d3226df4f))
