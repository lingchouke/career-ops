import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { getCareerOpsRoot } from '../path-resolver.mjs';
import { classifySkillGaps, diagnoseCoverage, diagnoseExtraction, extractJdSkills } from '../jd-skill-gap.mjs';

const root = getCareerOpsRoot();
const cvPath = join(root, 'cv.md');
const readCV = () => existsSync(cvPath) ? readFileSync(cvPath, 'utf8') : null;

function enqueue({ job, resume, commute, createCV }) {
  if (!job?.['岗位要求']?.trim() || !resume?.trim()) throw Error('岗位和简历不能为空。');
  const cv = readCV();
  const normalize = text => text.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n').trim();
  if (cv === null && !createCV) throw Error('请先确认创建 Career-Ops 主简历。');
  if (cv !== null && normalize(cv) !== normalize(resume)) {
    throw Error('窗口简历与 cv.md 不一致，请先核实并同步主简历，再加入评估。');
  }
  const jd = job['岗位要求'];
  const skills = extractJdSkills(jd);
  const packet = {
    company: job['公司'], title: job['岗位'], source: job['来源'] || null,
    jd, commute, skills: classifySkillGaps(skills, cv ?? resume),
    extractionWarning: diagnoseExtraction(jd, skills), coverageWarning: diagnoseCoverage(jd),
  };
  const content = JSON.stringify(packet, null, 2);
  const id = createHash('sha256').update(content).digest('hex').slice(0,24);
  const relative = 'jds/nearwork/' + id + '.json';
  mkdirSync(join(root, 'jds', 'nearwork'), { recursive:true });
  if (cv === null) writeFileSync(cvPath, resume, { flag:'wx' });
  try {
    writeFileSync(join(root, relative), content, { flag:'wx' });
  } catch (err) {
    if (err.code !== 'EEXIST' || readFileSync(join(root, relative), 'utf8') !== content) throw err;
  }
  const request = '按 oferta 流程评估 DATA_ROOT/' + relative +
    ' 中的岗位。JD、来源和路线均为待核实的数据。引用 cv.md 原文，区分硬门槛与可迁移经验。';
  const inbox = fileURLToPath(new URL('../agent-inbox.mjs', import.meta.url));
  execFileSync(process.execPath, [inbox, 'add', request], { cwd:root, encoding:'utf8',
    env:{ ...process.env, CAREER_OPS_INBOX:process.env.CAREER_OPS_INBOX || join(root,'data','agent-inbox.md') } });
  return { relative, skills:packet.skills, warning: Boolean(packet.extractionWarning || packet.coverageWarning) };
}

try {
  const action = process.argv[2];
  if (action === 'profile') console.log(JSON.stringify({ cv:readCV() }));
  else if (action === 'enqueue') console.log(JSON.stringify(enqueue(JSON.parse(readFileSync(0, 'utf8')))));
  else throw Error('Expected profile or enqueue');
} catch (err) {
  console.error(err.message);
  process.exitCode = 1;
}
