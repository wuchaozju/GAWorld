import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { execFileSync, spawnSync } from 'child_process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, '../../..');
const fixtureRoot = path.resolve(repoRoot, 'tests/fixtures/research_papers');
const manifestPath = path.join(fixtureRoot, 'fixture_manifest.json');
const generatorPath = path.join(fixtureRoot, 'generate_fixture_documents.py');

export interface ResearchFixture {
  id: string;
  title: string;
  citation: string;
  doi: string;
  expected_scenario_id: string;
  source_type: string;
  text: string;
}

export interface ResearchFixtureFiles {
  fixture: ResearchFixture;
  outputDir: string;
  txtPath: string;
  pdfPath: string;
  scannedPdfPath: string;
}

function resolvePython(): string {
  const virtualenvPython = process.platform === 'win32'
    ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, '.venv', 'bin', 'python');
  const candidates = [
    process.env.FOS_FIXTURE_PYTHON,
    virtualenvPython,
    'python',
    'python3',
  ].filter(Boolean) as string[];

  for (const candidate of candidates) {
    if (path.isAbsolute(candidate) && fs.existsSync(candidate)) {
      return candidate;
    }
    const probe = spawnSync(candidate, ['--version'], { stdio: 'ignore' });
    if (probe.status === 0) {
      return candidate;
    }
  }
  throw new Error('No Python runtime is available for generating research fixture files.');
}

function loadManifest(): ResearchFixture[] {
  return JSON.parse(fs.readFileSync(manifestPath, 'utf-8')) as ResearchFixture[];
}

export function getResearchFixture(fixtureId: string): ResearchFixture {
  const fixture = loadManifest().find((item) => item.id === fixtureId);
  if (!fixture) {
    throw new Error(`Unknown research fixture: ${fixtureId}`);
  }
  return fixture;
}

export function ensureResearchFixtureFiles(fixtureId: string): ResearchFixtureFiles {
  const fixture = getResearchFixture(fixtureId);
  const outputDir = path.join(os.tmpdir(), 'fos-research-fixtures', fixtureId);
  fs.mkdirSync(outputDir, { recursive: true });

  execFileSync(resolvePython(), [
    generatorPath,
    '--manifest',
    manifestPath,
    '--fixture-id',
    fixtureId,
    '--output-dir',
    outputDir,
  ]);

  return {
    fixture,
    outputDir,
    txtPath: path.join(outputDir, `${fixtureId}.txt`),
    pdfPath: path.join(outputDir, `${fixtureId}.pdf`),
    scannedPdfPath: path.join(outputDir, `${fixtureId}-scanned.pdf`),
  };
}
