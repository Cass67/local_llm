<script lang="ts">
  import type { ChatMessage } from '../../lib/chatApi';

  let { msg }: { msg: ChatMessage } = $props();
</script>

<div class="message" class:user={msg.role === 'user'} class:assistant={msg.role === 'assistant'}>
  <div class="role">{msg.role === 'user' ? 'You' : 'Assistant'}</div>
  <div class="content">{msg.content || '...'}</div>
</div>

<style>
  .message {
    padding: 0.6rem 1rem;
    border-radius: 12px;
    max-width: 85%;
    margin-bottom: 0.5rem;
  }
  .message.user {
    align-self: flex-end;
    background: var(--accent);
    border-bottom-right-radius: 2px;
  }
  .message.assistant {
    align-self: flex-start;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-bottom-left-radius: 2px;
  }
  .role {
    font-size: 0.7rem;
    color: var(--text-muted);
    margin-bottom: 0.2rem;
    text-transform: uppercase;
  }
  .content {
    white-space: pre-wrap;
    line-height: 1.5;
  }
</style>
