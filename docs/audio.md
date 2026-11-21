# Áudio no atendimento

## Resposta em áudio (TTS)

**Quando o agente responde em áudio** (regra no código: `app/application/audio_saida.py`):

- o cliente mandou **áudio na última mensagem** do turno; e
- a loja deixou ligada a opção "Responder em áudio quando o cliente mandar áudio" (perfil da loja,
  ligada por padrão); e
- há TTS configurado (`OPENAI_API_KEY` preenchida).

O texto da resposta **sempre** sai (preços e valores ficam por escrito); o áudio é uma segunda
mensagem, enviada logo depois. Respostas acima de 1200 caracteres não viram áudio. Qualquer falha
do TTS deixa só o texto, sem erro para o cliente.

**Provedor:** OpenAI `gpt-4o-mini-tts` (`POST /v1/audio/speech`), voz `coral` por padrão, com
instruções para português do Brasil. O formato `opus` (Ogg/Opus) é nativo, o mesmo da nota de voz do
WhatsApp, então não precisa de ffmpeg. A mídia gerada é guardada na mesma pasta das mídias do chat
(`MIDIA_DIR`) e servida em `GET /midias/<nome>`.

**Preço** (referência do anúncio do modelo em 2025: cerca de US$ 0,015 por minuto de fala; texto de
entrada a ~US$ 0,60 e áudio de saída a ~US$ 12 por milhão de tokens). **Confira o valor atual em
<https://openai.com/api/pricing> antes de contar com ele.** Uma resposta típica de vendas (~15 s)
custa uma fração de centavo.

**Configuração (`.env`):** `OPENAI_API_KEY` (vazia = só texto), `TTS_MODEL` (padrão
`gpt-4o-mini-tts`), `TTS_VOZ` (padrão `coral`).

**Canais:** WhatsApp (Evolution) recebe como nota de voz (`sendWhatsAppAudio`, base64); o chat web e
o simulador recebem o áudio com a URL da mídia e mostram um player.

Testes nunca chamam a API: usam `TTSFake` (`app/adapters/outbound/audio/tts_fake.py`) e o adaptador
da OpenAI é testado com `httpx.MockTransport`.
