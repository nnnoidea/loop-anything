// Each browser acceptance owns its platform, browser profile and working session.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {randomUUID} = require('node:crypto');
const {once} = require('node:events');
const {chromium} = require('playwright');

async function withPlatform(check) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'platform-ui-'));
  const env = {...process.env, LOOP_ANYTHING_IDENTITY_DIR: path.join(root, 'identity'),
    LOOP_ANYTHING_SPACES: path.join(root, 'spaces.json')};
  const server = spawn('python3', ['-m', 'loop_anything', '--db', path.join(root, 'db'),
    'serve', '--port', '0', '--allow-sleep'], {env, stdio: ['ignore', 'pipe', 'inherit']});
  let browser;
  try {
    const url = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Platform startup timed out')), 15000);
      let output = '';
      server.stdout.on('data', chunk => {
        output += chunk;
        const match = output.match(/Health check: (http:\/\/127\.0\.0\.1:\d+)\/api\/health/);
        if (match) {clearTimeout(timeout); resolve(match[1]);}
      });
      server.once('exit', code => {clearTimeout(timeout); reject(new Error('Platform exited: ' + code));});
    });

    async function api(route, data) {
      const options = data === undefined ? {} : {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-Loop-Anything': 'workspace'},
        body: JSON.stringify(data)
      };
      const response = await fetch(url + '/api/' + route, options);
      const result = await response.json();
      assert(response.ok, JSON.stringify(result));
      return result;
    }
    assert((await api('health')).ok);
    const tool = (tool, args) => api('tools', {tool, arguments: args});
    const bp = {
      schema_version: 2, id: 'browser', version: '1', name: '阅读与运行',
      description: '记录 <b>实验结果</b>', handbook: {instructions: 'Read the submitted facts.'},
      records: {text: {type: 'string'}, file: {type: 'string', format: 'file'}},
      nodes: {wait: {label: '观察进度', description: '观察用户提交的结果', instructions: 'Wait for result', inputs: {},
        outputs: {value: {record_type: 'text'}, report: {record_type: 'file'}}}}
    };
    const implementations = {wait: {options: {signal: {kind: 'event', event: 'measurement'}}, default: 'signal'}};
    const assets = Object.entries({
      'docs/flow.html': '<details open><summary>流程说明</summary><p style="height:1000px">获取结果后记录进度。</p><button data-loop-node="wait">观察进度</button></details>',
      'report.md': 'Ready'
    }).map(([path, content]) => ({path, base64: Buffer.from(content).toString('base64')}));
    const packed = await api('packages/export', {document: {loop_definition: bp, implementations}, assets});
    const {key} = await api('packages/install', {base64: packed.base64});

    async function startRun(title) {
      const turn = await api('runs', {key, title, request_id: randomUUID(), objective: title});
      const {token} = await tool('acquire_run',{run_id:turn.run_id});
      const operate = (tool, args) => api('runs/' + turn.run_id + '/agent', {tool, arguments: args, token});
      const added = await operate('add_task', {key: 'work', node_id: 'wait', inputs: {}});
      await operate('finish', {});
      return {turn, task: added.tasks[0].id};
    }

    browser = await chromium.launch({channel: 'chrome', headless: true});
    const page = await browser.newPage();
    page.setDefaultTimeout(10000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await check({url, api, tool, key, page, startRun});
    assert.deepEqual(errors, []);
  } finally {
    if (browser) await browser.close();
    if (server.exitCode === null && server.signalCode === null) {
      const stopped = once(server, 'exit');
      server.kill('SIGINT');
      await stopped;
    }
    fs.rmSync(root, {recursive: true, force: true});
  }
}
module.exports = {withPlatform, assert};
