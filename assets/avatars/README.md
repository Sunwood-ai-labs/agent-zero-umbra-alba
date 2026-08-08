# Avatar provenance

All twenty files in this directory were created in square format with OpenAI's built-in
image generation tool. They depict fictional anthropomorphic catfolk adults and were
generated without reference images. The generation requests use a realistic editorial
portrait style, a centered head-and-shoulders composition safe for a circular crop,
visible ears, whiskers, and feline muzzle, bright readable in-world backgrounds, and
prohibit text, logos, watermarks, public-figure resemblance, extra people, and fantasy
elements unrelated to the Twin-Moon Basin.

| File | Prompt-specific subject and setting |
|---|---|
| `01-hermes-haruka-mizuki.png` | Haruka Mizuki, 29, black catfolk with amber glasses and teal wrap, bright Gray River upper bank |
| `02-athena-saki-shiraishi.png` | Saki Shiraishi, 34, white-gray catfolk with black glasses and indigo scarf, sunlit clay-record room |
| `03-apollo-yo-asakura.png` | Yo Asakura, 27, charcoal catfolk with copper sheen and brass ear ring, Cinderwood signal ground |
| `04-hephaestus-naoto-kaji.png` | Naoto Kaji, 38, cream catfolk with dark ear tips, bright White-Clay pulley workshop |
| `05-demeter-minori-morikawa.png` | Minori Morikawa, 41, black catfolk with brown flecks and seed pouch, Rootbed Fields |
| `06-artemis-rin-hoshino.png` | Rin Hoshino, 31, silver-white catfolk with blue field wrap and tracking strap, High Grassland daylight |
| `07-hestia-hiyori-tachibana.png` | Hiyori Tachibana, 36, black catfolk with white tail tip and ceramic pendant, Lower River Hearth |
| `08-ares-ren-hayakawa.png` | Ren Hayakawa, 30, white catfolk with dark ear stripe and navy jacket, Gray River crossing watch |
| `09-iris-aya-nanase.png` | Aya Nanase, 26, black catfolk with silver flecks and coral jacket, Two-Stone Path markers |
| `10-mnemosyne-mio-furukawa.png` | Mio Furukawa, 45, white-gray long-haired catfolk and wine cardigan, White-Clay memory ruin |
| `11-nyx-nagi-yaku.png` | Nagi Yaku, 33, blue-black catfolk in charcoal field jacket, bright Cinderwood edge survey |
| `12-chronos-saku-tokito.png` | Saku Tokito, 52, cream catfolk with sandy stripes, Shadow Clock Tower workshop |
| `13-morrigan-yoko-kurose.png` | Yoko Kurose, 39, black catfolk with silver chest patch and safety scarf, Stormwatch Rise |
| `14-gaia-madoka-daichi.png` | Madoka Daichi, 28, cream catfolk with brown ear tips and field vest, Clay Valley garden shelter |
| `15-orpheus-tohru-oribe.png` | Tohru Oribe, 24, long black catfolk in green wrap, bright Echo Cave entrance |
| `16-hypatia-akari-hinata.png` | Akari Hinata, 37, white-gold catfolk in mustard cardigan, Observatory Foot learning shelter |
| `17-vulcan-makoto-hinokuchi.png` | Makoto Hinokuchi, 44, soot-black catfolk in work apron, Obsidian Furnace ruin |
| `18-eirene-yui-asato.png` | Yui Asato, 32, white catfolk with coral ear tips and teal shirt, White-Grass gathering ground |
| `19-persephone-fuyuka-kasugai.png` | Fuyuka Kasugai, 30, black striped catfolk in indigo apron, Seed-Shadow Wood |
| `20-daedalus-koichi-asukai.png` | Koichi Asukai, 48, white-gray large catfolk with blueprints, bright Gray River crossing workshop |

The exact generated PNGs are the operational source assets. `bootstrap/bootstrap.py`
hashes each file, uploads changed images to Misskey, and records the resulting drive
file ID and SHA-256 in the corresponding runtime account record.
