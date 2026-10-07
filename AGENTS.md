# AGENTS.md

このプロジェクト（hermes-updater）の運用ルールは [`CLAUDE.md`](CLAUDE.md) にある。**作業を始める前に `CLAUDE.md` を読むこと。**

## なぜこのファイルがあるか

OpenCode V2 は指示ファイルとして `AGENTS.md` のみを読み、`CLAUDE.md` は読まない
（<https://opencode.ai/v2/docs/instructions/>）。Claude Code 用の `CLAUDE.md` を
二重管理しないため、本ファイルは参照のみを置く。

## 秘密情報

`.env` / 認証情報は読まない・表示しない・転記しない。必要ならユーザーに依頼する
（全プロジェクト共通ルール: `~/.config/opencode/AGENTS.md`）。