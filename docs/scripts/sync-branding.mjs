import { cp, mkdir, rm } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const source = fileURLToPath(new URL('../../assets/branding/', import.meta.url))
const mapsSource = fileURLToPath(new URL('../../assets/maps/', import.meta.url))
const target = fileURLToPath(new URL('../public/', import.meta.url))
const mapsTarget = fileURLToPath(new URL('../public/maps/', import.meta.url))

await rm(target, { recursive: true, force: true })
await mkdir(target, { recursive: true })
await cp(source, target, { recursive: true })
await cp(mapsSource, mapsTarget, { recursive: true })
