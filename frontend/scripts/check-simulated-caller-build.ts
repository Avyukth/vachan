import { readFile } from 'node:fs/promises';
import { join } from 'node:path';

const CLIENT_OUTPUT = '.svelte-kit/output/client';
const mode = process.argv[2];
const forbiddenMarkers = [
	'SIMULATED CALLER',
	'happy_verification_and_promise',
	'SimulatedCallerControl',
	'simCaller'
] as const;

type ManifestEntry = {
	file: string;
	css?: string[];
	assets?: string[];
};

// SvelteKit retains obsolete hashed files between local builds. Its current Vite
// manifest is the authoritative deployable graph, so scan every asset it names plus
// source-controlled public files. Ignored local WAV evidence is deliberately outside
// the committed production artifact contract.
const manifest = JSON.parse(
	await readFile(join(CLIENT_OUTPUT, '.vite/manifest.json'), 'utf8')
) as Record<string, ManifestEntry>;
const manifestFiles = Object.values(manifest).flatMap((entry) => [
	entry.file,
	...(entry.css ?? []),
	...(entry.assets ?? [])
]);
const trackedStatic = Bun.spawnSync(['git', 'ls-files', '-z', '--', 'static']).stdout
	.toString()
	.split('\0')
	.filter(Boolean);
const files = [
	...new Set([
		...manifestFiles.map((path) => join(CLIENT_OUTPUT, path)),
		...trackedStatic
	])
];
const haystackParts = await Promise.all(
	files.map(async (path) => `${path}\n${await readFile(path, 'utf8').catch(() => '')}`)
);
const haystack = haystackParts.join('\n');
const found = forbiddenMarkers.filter((marker) => haystack.includes(marker));

if (mode === 'absent') {
	if (found.length > 0) {
		throw new Error(`Default client artifact exposes gated caller-input markers: ${found.join(', ')}`);
	}
	console.log('Default client artifact contains no simulated-caller label, fixture ID, or module.');
} else if (mode === 'enabled') {
	const required = forbiddenMarkers.slice(0, 2);
	const missing = required.filter((marker) => !haystack.includes(marker));
	if (missing.length > 0) {
		throw new Error(`Explicitly gated client artifact is missing: ${missing.join(', ')}`);
	}
	console.log('Explicitly gated client artifact includes durable caller-input disclosure.');
} else {
	throw new Error('Usage: bun scripts/check-simulated-caller-build.ts absent|enabled');
}
