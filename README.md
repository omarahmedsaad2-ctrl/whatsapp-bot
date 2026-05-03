---
title: WhatsApp Bot
emoji: 🤖
colorFrom: green
colorTo: blue
sdk: docker
pinned: false
---

# 🤖 WhatsApp AI Bot — Hugging Face Spaces

بوت واتساب ذكي يشتغل 24/7 على Hugging Face Spaces باستخدام Docker.

## المتطلبات (HF Secrets)

اضبط المتغيرات دي في **Settings > Secrets**:

| Secret | الوصف |
|---|---|
| `OLLAMA_API_KEY` | مفتاح API للـ Ollama Cloud |
| `OLLAMA_API_URL` | رابط السيرفر (مثال: `https://ollama.com`) |
| `MODEL_NAME` | اسم الموديل (مثال: `gpt-oss:120b-cloud`) |
| `DATABASE_URL` | رابط قاعدة بيانات PostgreSQL |

## الميزات
- ذاكرة مستمرة باستخدام PostgreSQL
- تذكيرات ذكية بالعربي المصري
- تعلم تلقائي من المحادثات
- Health check على port 7860
- Keep-alive لمنع السكون التلقائي
