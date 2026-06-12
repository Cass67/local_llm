<script lang="ts">
  import { streamChat, type ChatMessage } from '../../lib/chatApi';
  import { fetchCurrentModel } from '../../lib/api';
  import type { CurrentModelResponse } from '../../lib/types';
  import ChatMessageComponent from './ChatMessage.svelte';
  import { onMount } from 'svelte';

  let messages: ChatMessage[] = $state([
    { role: 'system', content: 'You are a helpful AI assistant.' },
  ]);
  let input: string = $state('');
  let streaming: boolean = $state(false);
  let currentModel: CurrentModelResponse | null = $state(null);
  let error: string = $state('');
  let abortController: AbortController | null = null;

  onMount(async () => {
    try {
      currentModel = await fetchCurrentModel();
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : String(e);
    }
  });

  async function send() {
    const text = input.trim();
    if (!text || streaming || !currentModel?.alias) return;

    input = '';
    error = '';
    messages = [...messages, { role: 'user', content: text }];
    messages = [...messages, { role: 'assistant', content: '' }];
    const assistantIdx = messages.length - 1;

    streaming = true;
    abortController = new AbortController();

    try {
      const modelName = `ubt26-llamacpp/${currentModel.alias}`;
      for await (const token of streamChat(modelName, messages.slice(0, -1), abortController.signal)) {
        messages = messages.map((m, i) =>
          i === assistantIdx ? { ...m, content: m.content + token } : m
        );
      }
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      error = e instanceof Error ? e.message : String(e);
    } finally {
      streaming = false;
      abortController = null;
    }
  }

  function stop() {
    abortController?.abort();
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }
</script>

<div class="chat-interface">
  {#if error}
    <div class="error">{error}</div>
  {/if}

  <div class="model-bar">
    Model: <strong>{currentModel?.alias || 'none selected'}</strong>
    {#if currentModel?.backend}
      <span class="backend-tag">{currentModel.backend}</span>
    {/if}
  </div>

  <div class="messages">
    {#each messages.filter(m => m.role !== 'system') as msg}
      <ChatMessageComponent {msg} />
    {/each}
    {#if messages.length <= 1}
      <div class="empty-chat">Send a message to start chatting with the active model.</div>
    {/if}
  </div>

  <div class="input-area">
    <textarea
      bind:value={input}
      onkeydown={handleKeydown}
      placeholder="Type a message... (Enter to send, Shift+Enter for newline)"
      disabled={streaming}
      rows={3}
    ></textarea>
    <div class="input-actions">
      {#if streaming}
        <button class="stop-btn" onclick={stop}>Stop</button>
      {:else}
        <button class="send-btn" onclick={send} disabled={!input.trim()}>Send</button>
      {/if}
    </div>
  </div>
</div>

<style>
  .chat-interface {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 6rem);
    gap: 0.5rem;
  }
  .error { background: var(--red); color: white; padding: 0.5rem; border-radius: 4px; font-size: 0.85rem; }
  .model-bar {
    padding: 0.3rem 0.5rem;
    background: var(--bg-card);
    border-radius: 4px;
    font-size: 0.85rem;
    flex-shrink: 0;
  }
  .backend-tag {
    margin-left: 0.5rem;
    font-size: 0.7rem;
    padding: 0.1rem 0.3rem;
    border-radius: 3px;
    background: var(--accent);
  }
  .messages {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .empty-chat { color: var(--text-muted); text-align: center; padding: 2rem; }
  .input-area {
    flex-shrink: 0;
    display: flex;
    gap: 0.5rem;
  }
  textarea {
    flex: 1;
    padding: 0.5rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--bg-card);
    color: var(--text);
    font-family: inherit;
    resize: none;
  }
  .input-actions { display: flex; align-items: flex-end; }
  .send-btn, .stop-btn {
    padding: 0.5rem 1rem;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-weight: bold;
  }
  .send-btn { background: var(--accent); color: var(--text); }
  .send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .stop-btn { background: var(--red); color: white; }
</style>
