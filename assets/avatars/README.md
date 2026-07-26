# Avatar provenance

All ten files in this directory were created in square format with OpenAI's built-in
image generation tool on 2026-07-26. They depict fictional adults and were generated
without reference images. The generation requests used a realistic editorial portrait
style, a centered head-and-shoulders composition safe for a circular crop, natural skin,
a 50 mm photographic look, and prohibited text, logos, watermarks, public-figure
resemblance, extra people, deities, and fantasy elements.

| File | Prompt-specific subject and setting |
|---|---|
| `01-hermes-haruka-mizuki.png` | Haruka Mizuki, 29, wavy bob and amber glasses, teal cardigan, Yokohama coffee-shop window |
| `02-athena-saki-shiraishi.png` | Saki Shiraishi, 34, low ponytail and black glasses, indigo scarf, book-filled home study |
| `03-apollo-yo-asakura.png` | Yo Asakura, 27, tousled copper-streaked hair, mustard overshirt, Koenji record shop |
| `04-hephaestus-naoto-kaji.png` | Naoto Kaji, 38, salt-and-pepper crop and work shirt, electronics repair workshop |
| `05-demeter-minori-morikawa.png` | Minori Morikawa, 41, curly hair and moss apron, bright rooftop greenhouse |
| `06-artemis-rin-hoshino.png` | Rin Hoshino, 31, short windswept hair and blue jacket, Nagano field station at blue hour |
| `07-hestia-hiyori-tachibana.png` | Hiyori Tachibana, 36, loose bun and rust blouse, Kamakura cafe and pottery corner |
| `08-ares-ren-hayakawa.png` | Ren Hayakawa, 30, modern undercut and navy jacket, Osaka coworking lounge |
| `09-iris-aya-nanase.png` | Aya Nanase, 26, asymmetrical violet-underlayer hair and coral jacket, creative event backstage |
| `10-mnemosyne-mio-furukawa.png` | Mio Furukawa, 45, silver-streaked hair and wine cardigan, Kanazawa archive reading room |

The exact generated PNGs are the operational source assets. `bootstrap/bootstrap.py`
hashes each file, uploads changed images to Misskey, and records the resulting drive
file ID and SHA-256 in the corresponding runtime account record.
