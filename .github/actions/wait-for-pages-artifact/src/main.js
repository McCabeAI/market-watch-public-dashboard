'use strict'

const core = require('@actions/core')
const { DefaultArtifactClient } = require('@actions/artifact')
const { formatResult, publicDetail, waitUntilVisible } = require('./wait')

async function listPagesArtifacts() {
  const client = new DefaultArtifactClient()
  // No options. deploy-pages uses this same unfiltered results-service list.
  const response = await client.listArtifacts()
  return response.artifacts
}

async function run(listOnce = listPagesArtifacts) {
  try {
    const result = await waitUntilVisible({
      name: core.getInput('name'),
      artifactId: core.getInput('artifact-id'),
      listOnce,
      sleep: (seconds) => new Promise((resolve) => {
        setTimeout(resolve, seconds * 1000)
      }),
    })
    const line = formatResult(result)
    if (result.status === 'visible') {
      core.info(line)
      return
    }
    core.setFailed(line)
  } catch (error) {
    core.setFailed(publicDetail(error))
  }
}

run()

module.exports = { listPagesArtifacts, run }
