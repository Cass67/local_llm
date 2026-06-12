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
    padding: 0.5rem 0.8rem;
    border-radius: 8px;
    max-width: 85%;
  }
  .message.user {
    align-self: flex-end;
    background: var(--accent);
  }
  .message.assistant {
    align-self: flex-start;
    background: var(--bg-card);
    border: 1px solid var(--border);
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
