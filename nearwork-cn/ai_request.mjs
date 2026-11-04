import { readFileSync } from 'node:fs';
import { assertLlmRequestAllowed } from '../lib/llm-outbound.mjs';

try {
  const { base, model, key, messages, limit } = JSON.parse(readFileSync(0, 'utf8'));
  const endpoint = new URL(base.replace(/\/+$/, '') + '/chat/completions');
  const local = ['localhost','127.0.0.1','[::1]'].includes(endpoint.hostname);
  if (endpoint.protocol !== 'https:' && !(local && endpoint.protocol === 'http:')) {
    throw Error('请使用安全的服务地址。');
  }
  const body = { model, messages, temperature: 0, stream: false, response_format: { type: 'json_object' } };
  body[endpoint.hostname === 'api.openai.com' ? 'max_completion_tokens' : 'max_tokens'] = limit;
  const payload = JSON.stringify(body);
  try {
    assertLlmRequestAllowed(endpoint.href, payload, { allowRedact: false });
  } catch {
    throw Error('材料包含受保护的信息，请使用脱敏后的简历或岗位描述。');
  }
  const headers = { 'Content-Type': 'application/json' };
  if (key) headers.Authorization = 'Bearer ' + key;
  const response = await fetch(endpoint, { method:'POST', headers, body:payload,
    redirect:'error', signal:AbortSignal.timeout(150000) });
  if (!response.ok) throw Error('AI 服务未完成请求（' + response.status + '），请检查服务设置或稍后重试。');
  const choice = (await response.json()).choices?.[0];
  console.log(JSON.stringify({ finish:choice?.finish_reason, content:choice?.message?.content }));
} catch (error) {
  console.error(/^(材料包含|请使用|AI 服务未完成)/.test(error.message) ? error.message : '无法连接 AI 服务或读取回复，请检查设置后重试。');
  process.exitCode = 1;
}
