'use strict'

const MAX_ATTEMPTS = 8
const MAX_DELAY_SECONDS = 16

function delayBeforeNext(index) {
  if (!Number.isInteger(index) || index < 0) {
    const error = new Error('delay index must be non-negative')
    error.permanent = true
    throw error
  }
  return Math.min(2 * 2 ** index, MAX_DELAY_SECONDS)
}

function requireExactName(name) {
  if (typeof name !== 'string' || name.length === 0 || /\s/.test(name)) {
    const error = new Error('artifact name must be an exact non-empty token')
    error.permanent = true
    throw error
  }
  return name
}

function requireExactId(value) {
  if (typeof value === 'boolean' || typeof value === 'string' && !/^\d+$/.test(value)) {
    const error = new Error('artifact id must be a positive integer')
    error.permanent = true
    throw error
  }
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    const error = new Error('artifact id must be a positive integer')
    error.permanent = true
    throw error
  }
  return parsed
}

function permanentError(message) {
  const error = new Error(message)
  error.permanent = true
  return error
}

function isPermanentMetadataError(error) {
  if (error && error.permanent === true) {
    return true
  }
  const text = String((error && error.message) || error)
  return /\b(401|403)\b/.test(text) || /unauthorized/i.test(text)
}

function publicDetail(error) {
  return String((error && error.message) || error)
    .replace(/Bearer\s+\S+/gi, 'Bearer [redacted]')
    .replace(/ACTIONS_RUNTIME_TOKEN=\S+/g, 'ACTIONS_RUNTIME_TOKEN=[redacted]')
    .slice(0, 300)
}

function interpretListing(rows, name, artifactId) {
  const expectedName = requireExactName(name)
  const expectedId = requireExactId(artifactId)
  if (!Array.isArray(rows)) {
    throw permanentError('artifact listing is not a list')
  }
  const seen = []
  const exact = []
  for (const row of rows) {
    if (!row || typeof row.name !== 'string' || !Number.isSafeInteger(row.id) || row.id <= 0) {
      throw permanentError('artifact listing row is missing an exact name or id')
    }
    seen.push([row.name, row.id])
    if (row.name === expectedName) {
      exact.push(row)
    }
  }
  if (exact.length > 1) {
    return {
      status: 'ambiguous',
      retryable: false,
      name: expectedName,
      seen,
      detail: 'multiple artifacts have the exact name',
    }
  }
  if (exact.length === 1) {
    if (exact[0].id !== expectedId) {
      return {
        status: 'id_mismatch',
        retryable: false,
        name: exact[0].name,
        artifactId: exact[0].id,
        seen,
        detail: 'exact name is listed with a different id',
      }
    }
    return {
      status: 'visible',
      retryable: false,
      name: exact[0].name,
      artifactId: exact[0].id,
      seen,
    }
  }
  return {
    status: 'not_visible',
    retryable: true,
    name: expectedName,
    seen,
    detail: 'exact name is not in the listing',
  }
}

async function waitUntilVisible({ name, artifactId, listOnce, sleep, attempts = MAX_ATTEMPTS }) {
  const expectedName = requireExactName(name)
  const expectedId = requireExactId(artifactId)
  if (!Number.isInteger(attempts) || attempts < 1 || attempts > MAX_ATTEMPTS) {
    throw permanentError(`attempts must be an integer from 1 to ${MAX_ATTEMPTS}`)
  }
  let result = {
    status: 'not_visible',
    retryable: true,
    name: expectedName,
    detail: 'not started',
    attempts: 0,
    seen: [],
  }
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const rows = await listOnce()
      const interpreted = interpretListing(rows, expectedName, expectedId)
      result = { ...interpreted, attempts: attempt }
    } catch (error) {
      const permanent = isPermanentMetadataError(error)
      result = {
        status: 'metadata_error',
        retryable: !permanent,
        attempts: attempt,
        name: expectedName,
        seen: [],
        detail: publicDetail(error),
      }
      if (permanent) {
        return result
      }
    }
    if (result.status === 'visible' || result.retryable === false) {
      return result
    }
    if (attempt === attempts) {
      return result
    }
    await sleep(delayBeforeNext(attempt - 1))
  }
  return result
}

function formatResult(result) {
  const seen = (result.seen || [])
    .slice(0, 20)
    .map(([seenName, seenId]) => `${seenName}:${seenId}`)
    .join(',')
  if (result.status === 'visible') {
    return `visible name=${result.name} id=${result.artifactId} attempts=${result.attempts}`
  }
  const parts = [`${result.status} attempts=${result.attempts}`]
  if (seen) {
    parts.push(`seen=${seen}`)
  }
  if (result.detail) {
    parts.push(`detail=${result.detail}`)
  }
  return parts.join(' ')
}

module.exports = {
  MAX_ATTEMPTS,
  delayBeforeNext,
  formatResult,
  interpretListing,
  isPermanentMetadataError,
  publicDetail,
  requireExactId,
  requireExactName,
  waitUntilVisible,
}
