// Teste de carga do webhook da Evolution (POST /webhooks/evolution, evento messages.upsert).
//
// Simula muitos leads mandando mensagens em rajadas (exercita o debounce e a trava por conversa),
// com reentrega do mesmo id (idempotencia). A volta para o cliente vai para uma Evolution falsa
// (infra/k6/stub_evolution.py) e o LLM e simulado (LLM_FAKE_LATENCIA_MS): nada custa e nada sai.
//
// Normalmente chamado por infra/k6/rodar_carga.sh. Variaveis (-e CHAVE=valor):
//   BASE_URL (http://localhost:8100)   LOJA_ID (loja demo)   WEBHOOK_TOKEN (token-carga)
//   RATE_POR_MIN (400 = 10x o pico)    DURACAO_S (300)       LEADS (250)
//   REENTREGA_A_CADA (20)              PREFIXO (carga-)      RUN_ID (obrigatorio p/ checagem)
//
// Cada requisicao gera um ponto da metrica `msg_enviada` com as tags id_wa/status/resultado/numero;
// `k6 run --out json=...` os grava e `backend/scripts/checar_contagem.py` compara com o banco.

import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import exec from 'k6/execution';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8100';
const LOJA_ID = __ENV.LOJA_ID || '00000000-0000-4000-8000-00000000de30';
const TOKEN = __ENV.WEBHOOK_TOKEN || 'token-carga';
const RATE_POR_MIN = Number(__ENV.RATE_POR_MIN || 400);
const DURACAO_S = Number(__ENV.DURACAO_S || 300);
const LEADS = Number(__ENV.LEADS || 250);
const REENTREGA_A_CADA = Number(__ENV.REENTREGA_A_CADA || 20);
const PREFIXO = __ENV.PREFIXO || 'carga-';
const RUN_ID = __ENV.RUN_ID || Date.now().toString(36);

export const msgEnviada = new Counter('msg_enviada');

export const options = {
  scenarios: {
    webhooks: {
      executor: 'constant-arrival-rate',
      rate: RATE_POR_MIN,
      timeUnit: '1m',
      duration: `${DURACAO_S}s`,
      preAllocatedVUs: 50,
      maxVUs: 400,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
    checks: ['rate>0.99'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const TEXTOS = [
  'Oi, tudo bem? Vocês têm iPhone 16?',
  'Quanto tá o de 128GB?',
  'Aceita meu iPhone 13 na troca?',
  'Dá pra parcelar em 10x?',
  'Qual a cor que tem pronta entrega?',
  'Tem garantia? Quanto tempo?',
  'Se eu pagar no pix tem desconto?',
  'Pode me mandar uns detalhes do Samsung S24?',
  'Fecho hoje se der pra baixar um pouco',
  'Retiro na loja ainda hoje, até que horas abre?',
];
const RAJADAS = [1, 3, 2, 1, 4, 2, 1, 3];

// Plano deterministico (igual em todos os VUs): mensagem i -> (lead, sequencia do lead).
// Mensagens consecutivas do mesmo lead formam uma rajada (1 a 4), como no WhatsApp real.
const TOTAL_PLANO = Math.ceil((RATE_POR_MIN / 60) * DURACAO_S * 1.3) + 100;
const PLANO_LEAD = [];
const PLANO_SEQ = [];
(function montarPlano() {
  const contagem = {};
  let grupo = 0;
  while (PLANO_LEAD.length < TOTAL_PLANO) {
    const lead = grupo % LEADS;
    const tamanho = RAJADAS[grupo % RAJADAS.length];
    for (let k = 0; k < tamanho && PLANO_LEAD.length < TOTAL_PLANO; k++) {
      contagem[lead] = (contagem[lead] || 0) + 1;
      PLANO_LEAD.push(lead);
      PLANO_SEQ.push(contagem[lead]);
    }
    grupo++;
  }
})();

function pad(n, largura) {
  return String(n).padStart(largura, '0');
}

function numeroDoLead(lead) {
  return `5511988${pad(lead, 6)}`;
}

function idWhatsapp(lead, seq) {
  return `${PREFIXO}${RUN_ID}-L${pad(lead, 4)}-M${pad(seq, 4)}`;
}

function corpo(lead, seq, idWa) {
  return JSON.stringify({
    event: 'messages.upsert',
    instance: `loja-${LOJA_ID}`,
    data: {
      key: { remoteJid: `${numeroDoLead(lead)}@s.whatsapp.net`, fromMe: false, id: idWa },
      pushName: `Cliente ${lead}`,
      message: { conversation: TEXTOS[(lead + seq) % TEXTOS.length] },
      messageType: 'conversation',
      messageTimestamp: Math.floor(Date.now() / 1000),
    },
  });
}

function registrar(res, idWa, numero, reentrega) {
  let resultado = '';
  try {
    resultado = res.json('resultado') || '';
  } catch (e) {
    resultado = '';
  }
  const ok = check(res, {
    'webhook 200': (r) => r.status === 200,
    'resultado processada/duplicada': () => resultado === 'processada' || resultado === 'duplicada',
  });
  msgEnviada.add(1, {
    id_wa: idWa,
    numero,
    status: String(res.status),
    resultado,
    reentrega: reentrega ? '1' : '0',
    ok: ok ? '1' : '0',
  });
}

export default function () {
  const i = exec.scenario.iterationInTest;
  const lead = PLANO_LEAD[i % TOTAL_PLANO];
  const seq = PLANO_SEQ[i % TOTAL_PLANO] + Math.floor(i / TOTAL_PLANO) * 1000;
  const idWa = idWhatsapp(lead, seq);
  const numero = numeroDoLead(lead);
  const url = `${BASE_URL}/webhooks/evolution`;
  const params = {
    headers: { 'Content-Type': 'application/json', 'X-Webhook-Token': TOKEN },
    tags: { name: 'webhook_evolution' },
  };
  const body = corpo(lead, seq, idWa);

  if (REENTREGA_A_CADA > 0 && i % REENTREGA_A_CADA === 7) {
    // Reentrega simultanea do mesmo id (a Evolution reenvia sem esperar o 200): teste de idempotencia.
    const respostas = http.batch([
      ['POST', url, body, params],
      ['POST', url, body, params],
    ]);
    registrar(respostas[0], idWa, numero, false);
    registrar(respostas[1], idWa, numero, true);
    return;
  }
  registrar(http.post(url, body, params), idWa, numero, false);
}
