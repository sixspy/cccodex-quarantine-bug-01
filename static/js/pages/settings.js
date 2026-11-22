import { api } from '../api.js';

export async function renderSettings(el) {
  const [data, overview, gate] = await Promise.all([
    api('/api/settings'),
    api('/api/enter_pack/overview'),
    api('/api/enter_pack/gate'),
  ]);
  el.innerHTML = `
    <div class="card">
      <h2>台参数</h2>
      <table>
        <thead><tr><th>项</th><th>说明</th><th>值</th><th></th></tr></thead>
        <tbody>
          ${(data.items || []).map((s) => `
            <tr>
              <td>${s.key}</td>
              <td>${s.label}</td>
              <td><input data-key="${s.key}" value="${s.value}" /></td>
              <td><button data-save="${s.key}">保存</button></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>入舱口径（只读）</h2>
      <p class="muted">甲边：切流账册锁定入舱瞬间条目键 + 舱码指纹，落点行拒回刷；清洗编排读账册现行引用。此页只照不写。</p>
      <div class="stat-strip">
        <div class="stat"><span class="muted">入舱标记</span><b>${overview.chip}</b></div>
        <div class="stat"><span class="muted">坏件余数</span><b class="${overview.bad_remainder ? 'hot' : ''}">${overview.bad_remainder}</b></div>
        <div class="stat"><span class="muted">入舱落点</span><b>${overview.landing_count}</b></div>
        <div class="stat"><span class="muted">现行读引用</span><b>${overview.active_read}</b></div>
        <div class="stat"><span class="muted">清洗闸门</span><b class="${gate.allowed ? 'okText' : 'badText'}">${gate.allowed ? '开' : '闭'}</b></div>
      </div>
      <p class="muted">最新落点指纹 ${overview.latest_fingerprint || '空'} · 入舱标记条目 ${gate.marked_count} / 落点行 ${gate.landing_count}</p>
      ${gate.reasons.length
        ? `<div class="hint-box bad">闸门闭：${gate.reasons.join('；')}</div>`
        : '<div class="hint-box">闸门开：入舱标记均有落点行，指纹未拧花。</div>'}
    </div>`;
  el.querySelectorAll('[data-save]').forEach((btn) => {
    btn.onclick = async () => {
      const input = el.querySelector(`input[data-key="${btn.dataset.save}"]`);
      await api('/api/settings/update', {
        method: 'POST',
        body: JSON.stringify({ key: btn.dataset.save, value: input.value }),
      });
      await renderSettings(el);
    };
  });
}
