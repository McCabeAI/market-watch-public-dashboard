'use strict'

const assert = require('node:assert/strict')
const { spawnSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const {
  MAX_ATTEMPTS,
  delayBeforeNext,
  formatResult,
  interpretListing,
  waitUntilVisible,
} = require('./wait')

const ACTION = path.resolve(__dirname, '..')
const REPO = path.resolve(ACTION, '../../..')
const PRIOR_NAME = 'github-pages-research-45370439017-1'
const NEW_NAME = 'github-pages-research-45370439017-2'
const ATTEMPT1_ID = 14910118264
const ATTEMPT2_ID = 14916005309

test('delayed visibility does not accept an empty list or a prior attempt', async () => {
  const listings = [
    [],
    [{ name: PRIOR_NAME, id: ATTEMPT1_ID }],
    [
      { name: PRIOR_NAME, id: ATTEMPT1_ID },
      { name: NEW_NAME, id: ATTEMPT2_ID },
    ],
  ]
  const sleeps = []
  const result = await waitUntilVisible({
    name: NEW_NAME,
    artifactId: ATTEMPT2_ID,
    listOnce: async () => listings.shift(),
    sleep: async (seconds) => {
      sleeps.push(seconds)
    },
    attempts: 8,
  })
  assert.equal(result.status, 'visible')
  assert.equal(result.attempts, 3)
  assert.equal(result.artifactId, ATTEMPT2_ID)
  assert.deepEqual(sleeps, [delayBeforeNext(0), delayBeforeNext(1)])
  assert.equal(listings.length, 0)
  assert.doesNotMatch(formatResult(result), /deployments/)
})

test('timeout keeps the prior artifact and does not treat it as visible', async () => {
  const sleeps = []
  const result = await waitUntilVisible({
    name: NEW_NAME,
    artifactId: ATTEMPT2_ID,
    listOnce: async () => [{ name: PRIOR_NAME, id: ATTEMPT1_ID }],
    sleep: async (seconds) => {
      sleeps.push(seconds)
    },
    attempts: 3,
  })
  assert.equal(result.status, 'not_visible')
  assert.equal(result.attempts, 3)
  assert.deepEqual(result.seen, [[PRIOR_NAME, ATTEMPT1_ID]])
  assert.deepEqual(sleeps, [2, 4])
  assert.match(formatResult(result), new RegExp(`${PRIOR_NAME}:${ATTEMPT1_ID}`))
})

test('name equality is exact', () => {
  const rows = [
    { name: 'github-pages-1', id: 10 },
    { name: 'github-pages-10', id: 11 },
    { name: 'github-pages', id: 12 },
  ]
  for (const [name, artifactId] of [
    ['github-pages-1', 10],
    ['github-pages-10', 11],
    ['github-pages', 12],
  ]) {
    const result = interpretListing(rows, name, artifactId)
    assert.equal(result.status, 'visible')
    assert.equal(result.artifactId, artifactId)
  }
  assert.equal(interpretListing(rows, 'github-pages-2', 99).status, 'not_visible')
})

test('a different id or a duplicate name stops without another poll', async () => {
  let calls = 0
  const mismatch = await waitUntilVisible({
    name: NEW_NAME,
    artifactId: ATTEMPT2_ID,
    listOnce: async () => {
      calls += 1
      return [{ name: NEW_NAME, id: ATTEMPT1_ID }]
    },
    sleep: async () => {
      throw new Error('slept')
    },
  })
  assert.equal(mismatch.status, 'id_mismatch')
  assert.equal(mismatch.retryable, false)
  assert.equal(calls, 1)

  calls = 0
  const ambiguous = await waitUntilVisible({
    name: NEW_NAME,
    artifactId: ATTEMPT2_ID,
    listOnce: async () => {
      calls += 1
      return [
        { name: NEW_NAME, id: ATTEMPT2_ID },
        { name: NEW_NAME, id: ATTEMPT2_ID + 1 },
      ]
    },
    sleep: async () => {
      throw new Error('slept')
    },
  })
  assert.equal(ambiguous.status, 'ambiguous')
  assert.equal(calls, 1)
})

test('a transient metadata error is retried and an auth error is not', async () => {
  let calls = 0
  const sleeps = []
  const recovered = await waitUntilVisible({
    name: NEW_NAME,
    artifactId: ATTEMPT2_ID,
    listOnce: async () => {
      calls += 1
      if (calls === 1) {
        throw new Error('results list HTTP 503')
      }
      return [{ name: NEW_NAME, id: ATTEMPT2_ID }]
    },
    sleep: async (seconds) => {
      sleeps.push(seconds)
    },
    attempts: 4,
  })
  assert.equal(recovered.status, 'visible')
  assert.equal(recovered.attempts, 2)
  assert.deepEqual(sleeps, [2])

  calls = 0
  const denied = await waitUntilVisible({
    name: NEW_NAME,
    artifactId: String(ATTEMPT2_ID),
    listOnce: async () => {
      calls += 1
      throw new Error('results list unauthorized HTTP 403')
    },
    sleep: async () => {
      throw new Error('slept')
    },
  })
  assert.equal(denied.status, 'metadata_error')
  assert.equal(denied.retryable, false)
  assert.equal(calls, 1)
  assert.doesNotMatch(formatResult(denied), /Bearer /)
})

test('the first exact listing does not sleep and the attempt bound is closed', async () => {
  const result = await waitUntilVisible({
    name: 'github-pages-1',
    artifactId: 42,
    listOnce: async () => [{ name: 'github-pages-1', id: 42 }],
    sleep: async () => {
      throw new Error('slept')
    },
  })
  assert.equal(result.status, 'visible')
  assert.equal(result.attempts, 1)
  await assert.rejects(
    () => waitUntilVisible({
      name: NEW_NAME,
      artifactId: ATTEMPT2_ID,
      listOnce: async () => [],
      sleep: async () => {},
      attempts: MAX_ATTEMPTS + 1,
    }),
    /attempts must be an integer/,
  )
  assert.equal(delayBeforeNext(0), 2)
  assert.equal(delayBeforeNext(3), 16)
  assert.equal(delayBeforeNext(6), 16)
})

test('invalid name or id never lists artifacts', async () => {
  await assert.rejects(
    () => waitUntilVisible({
      name: 'github pages',
      artifactId: 1,
      listOnce: async () => {
        throw new Error('listed')
      },
      sleep: async () => {},
    }),
    /exact non-empty token/,
  )
  await assert.rejects(
    () => waitUntilVisible({
      name: NEW_NAME,
      artifactId: '0',
      listOnce: async () => {
        throw new Error('listed')
      },
      sleep: async () => {},
    }),
    /positive integer/,
  )
})

test('the action entrypoint uses the deploy-pages list call', () => {
  const manifest = fs.readFileSync(path.join(ACTION, 'action.yml'), 'utf8')
  const main = fs.readFileSync(path.join(ACTION, 'src/main.js'), 'utf8')
  const bundle = fs.readFileSync(path.join(ACTION, 'dist/index.js'), 'utf8')
  assert.match(manifest, /^runs:\n  using: node20\n  main: dist\/index\.js\n/m)
  assert.match(main, /client\.listArtifacts\(\)/)
  assert.doesNotMatch(main, /findBy|nameFilter|idFilter|ACTIONS_RUNTIME_TOKEN|ACTIONS_RESULTS_URL/)
  assert.match(bundle, /listArtifacts/)
  assert.doesNotMatch(main, /pages\/deployments/)
})

test('the bundled node entrypoint fails closed and does not print the runtime token', () => {
  const secret = 'super-secret-runtime-token-value'
  const result = spawnSync(process.execPath, ['dist/index.js'], {
    cwd: ACTION,
    env: {
      ...process.env,
      INPUT_NAME: '',
      'INPUT_ARTIFACT-ID': '',
      ACTIONS_RUNTIME_TOKEN: secret,
      ACTIONS_RESULTS_URL: 'https://results.example.test/api',
    },
    encoding: 'utf8',
  })
  assert.notEqual(result.status, 0)
  const output = `${result.stdout}${result.stderr}`
  assert.equal(output.includes(secret), false)
  assert.match(output, /artifact name must be an exact non-empty token/)
})

test('both publication workflows call this action once before one deploy', () => {
  const launch = fs.readFileSync(path.join(REPO, '.github/workflows/launch-market-watch.yml'), 'utf8')
  const deploy = fs.readFileSync(path.join(REPO, '.github/workflows/deploy-pages.yml'), 'utf8')
  for (const workflow of [launch, deploy]) {
    assert.equal(workflow.split('uses: ./.github/actions/wait-for-pages-artifact').length - 1, 1)
    assert.equal(workflow.includes('ACTIONS_RUNTIME_TOKEN'), false)
    assert.equal(workflow.includes('ACTIONS_RESULTS_URL'), false)
    assert.equal(workflow.includes('scripts.market_watch_launch.pages_artifact_visibility'), false)
  }
  assert.match(launch, /artifact-id: \$\{\{ steps\.pages-artifact\.outputs\.artifact_id \}\}/)
  assert.match(deploy, /pages_artifact_id: \$\{\{ steps\.pages-artifact\.outputs\.artifact_id \}\}/)
  assert.match(deploy, /artifact-id: \$\{\{ needs\.build\.outputs\.pages_artifact_id \}\}/)
  const research = launch.split('  research:\n')[1].split('  handoff:\n')[0]
  const finalDeploy = deploy.split('  deploy:\n')[1].split('  reconcile:\n')[0]
  assert.equal(research.split('actions/deploy-pages@v4').length - 1, 1)
  assert.equal(finalDeploy.split('actions/deploy-pages@v4').length - 1, 1)
  assert.match(research, /steps\.visibility\.outcome == 'success'/)
  assert.match(finalDeploy, /steps\.visibility\.outcome == 'success'/)
  const researchWait = research.indexOf('Wait for exact Pages artifact visibility')
  const researchDeploy = research.indexOf('Deploy to GitHub Pages')
  assert.ok(researchWait > 0 && researchWait < researchDeploy)
  const finalWait = finalDeploy.indexOf('Wait for exact Pages artifact visibility')
  const finalDeployStep = finalDeploy.indexOf('Deploy to GitHub Pages')
  assert.ok(finalWait > 0 && finalWait < finalDeployStep)
})
