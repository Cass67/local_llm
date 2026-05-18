# README Refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite the README into a practical operator guide for local OpenCode and llama.cpp profiles.

**Architecture:** Keep documentation in one top-level `README.md`. Lead with recommended commands, then explain model families, wrapper behavior, installation, operations, and troubleshooting.

**Tech Stack:** Markdown, Bash command examples, existing local LLM scripts.

---

### Task 1: Rewrite README

**Files:**
- Modify: `README.md`

**Steps:**
1. Replace existing README with a purpose-first guide.
2. Add quick command table.
3. Add model-family sections with profile tables.
4. Add install, operations, environment overrides, verification, and troubleshooting sections.

### Task 2: Verify

**Files:**
- Read: `README.md`

**Steps:**
1. Re-read README for accuracy against `scripts/oc-local` and `scripts/start*.sh`.
2. Run shell syntax/tests to confirm referenced scripts still pass.
3. Run `oc-qwen-coder-reliable --lean --info` and `oc-gemma-vision-reliable --lean --info` to validate examples.
