/* SPDX-License-Identifier: MIT */
class CamperInetFaultCard extends HTMLElement {
  constructor() { super(); this.attachShadow({mode:'open'}); }
  setConfig(config) {
    this._config = {entity:'sensor.truma_inet_meldungen', seen_entity:'button.truma_inet_meldungen_gesehen', restart_entity:'script.truma_heizung_neu_starten', ...config};
    this.shadowRoot.innerHTML = `<style>
      :host{display:block}ha-card{padding:20px}h2{font-size:20px;margin:0 0 12px}
      #status{font-weight:600}#status.warn{color:var(--warning-color,#d5a030)}
      .note{font-size:13px;color:var(--secondary-text-color);line-height:1.5;margin:8px 0}
      .incident{padding:12px;margin:12px 0;border-radius:12px;background:var(--secondary-background-color);overflow-wrap:anywhere}
      .code{font-size:18px;font-weight:600;white-space:pre-wrap}.history{font-size:13px;margin:10px 0;line-height:1.5;overflow-wrap:anywhere}
      button{font:inherit;padding:9px 14px;border:0;border-radius:10px;background:var(--secondary-background-color);color:var(--primary-text-color);cursor:pointer;margin:8px 0}
      button:disabled{opacity:.5;cursor:default}summary{cursor:pointer;font-size:14px;margin-top:12px}
    </style><ha-card><h2>Meldungen</h2><div id="status"></div><div class="note" id="fresh"></div>
      <div id="active"></div><div class="note" id="reset"></div><button id="seen">Als gesehen markieren</button>
      <button id="restart">Heizung neu starten</button>
      <div class="note" id="result"></div><details><summary>Verlauf</summary><div id="history"></div></details></ha-card>`;
    this.shadowRoot.getElementById('seen').onclick=async()=>{
      const result=this.shadowRoot.getElementById('result');
      try { await this._hass.callService('button','press',{entity_id:this._config.seen_entity});
        result.textContent='Gesehen angefordert · kein Gerätefehler wird zurückgesetzt.';
      } catch(e) { result.textContent='Bestätigung fehlgeschlagen. Bitte erneut prüfen.'; }
    };
    this.shadowRoot.getElementById('restart').onclick=async()=>{
      if(this._starting || this.shadowRoot.getElementById('restart').disabled) return;
      if(!window.confirm('Ist die Ursache behoben und darf die Heizung wieder anlaufen? Raumheizung und Warmwasser werden einmal ausgeschaltet und nach drei Minuten auf die bisherigen Werte gestellt. Ein Fehlerreset ist nicht garantiert.')) return;
      this._starting=true; this._render();
      const result=this.shadowRoot.getElementById('result');
      result.textContent='Neustart läuft · Rückmeldungen werden geprüft …';
      try {
        await this._hass.callService('script',this._config.restart_entity.slice(7),{cause_resolved:true});
        result.textContent='Ablauf beendet. Das Prüfergebnis steht in den Home-Assistant-Benachrichtigungen.';
      } catch(e) {
        result.textContent='Neustart nicht erfolgreich bestätigt. Meldungen und Benachrichtigungen prüfen; es folgt kein automatischer weiterer Versuch.';
      } finally { this._starting=false; this._render(); }
    };
    this._render();
  }
  set hass(hass) { this._hass=hass; this._render(); }
  _render() {
    if (!this._hass || !this._config) return;
    const entity=this._hass.states[this._config.entity], a=entity?.attributes || {};
    const available=entity && !['unavailable','unknown'].includes(entity.state);
    const time=v=>{const d=new Date(v);return v && Number.isFinite(d.getTime())?d.toLocaleString(this._hass.locale?.language || 'de-DE'):'—';};
    const byId=id=>this.shadowRoot.getElementById(id);
    byId('status').textContent=available?entity.state:'Fehlerstatus nicht erreichbar';
    byId('status').className=available && a.fresh && !a.active?.length?'':'warn';
    byId('fresh').textContent=(available && a.fresh?'Zuletzt geprüft: ':'Letzter bekannter Stand: ')+time(a.checked);
    const active=byId('active');active.replaceChildren();
    for(const item of a.active || []) {
      const row=document.createElement('div');row.className='incident';
      const code=document.createElement('div');code.className='code';code.textContent=item.device+' · '+item.code;
      const note=document.createElement('div');note.className='note';
      note.textContent=({warning:'Warnung',error:'Störung',command:'Nicht bestätigt',unknown:'Unbekannte Meldung'}[item.severity] || 'Meldung')+
        ' · seit '+time(item.occurred)+(item.seen?' · Gesehen':' · Neu')+
        (!available || item.stale?' · Noch nicht erneut geprüft':'');
      row.append(code,note);active.append(row);
    }
    const restart=this._hass.states[this._config.restart_entity];
    const canRestart=this._config.restart_entity?.startsWith('script.') && restart && !['unavailable','unknown'].includes(restart.state);
    byId('reset').textContent=a.active?.some(x=>x.source!=='command')?
      'Ursache zuerst beheben. „Gesehen“ bestätigt nur die Meldung. Ein Neustart schaltet aus und wieder ein; er garantiert keinen Fehlerreset.':'';
    byId('restart').hidden=!canRestart;
    byId('restart').disabled=!available || !a.fresh || this._starting || restart?.state==='on' ||
      this._hass.states['binary_sensor.truma_inet_verbindung']?.state!=='on' ||
      this._hass.states['sensor.truma_inet_timer']?.state!=='Aus' ||
      (this._hass.states['climate.truma_inet_heizung']?.state==='off' && this._hass.states['select.truma_inet_warmwasser']?.state==='Aus');
    byId('restart').textContent=this._starting || restart?.state==='on'?'Neustart läuft …':'Heizung neu starten';
    byId('seen').hidden=!a.active?.length;
    byId('seen').disabled=!available || !a.active?.some(x=>!x.seen);
    const history=byId('history');history.replaceChildren();
    for(const item of [...(a.history || [])].reverse()) {
      const row=document.createElement('div');row.className='history';
      row.textContent=time(item.at)+' · '+item.device+' · '+item.code+' · '+
        ({occurred:'Aufgetreten',seen:'Gesehen',resolved:'Nicht mehr gemeldet'}[item.change] || item.change);
      history.append(row);
    }
    if(!a.history?.length) history.textContent='Noch keine Meldungen erfasst.';
  }
  getCardSize() { return 3; }
  getGridOptions() { return {columns:12,min_columns:6,min_rows:2}; }
}
if(!customElements.get('camper-inet-fault-card')) customElements.define('camper-inet-fault-card',CamperInetFaultCard);
window.customCards=window.customCards || [];
window.customCards.push({type:'camper-inet-fault-card',name:'Truma Meldungen',description:'Gerätemeldungen, Aktualität und Verlauf'});
