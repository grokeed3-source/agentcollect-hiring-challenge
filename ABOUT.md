# About My Last Project: OmniAI CRM

OmniAI CRM is a multi-tenant SaaS platform featuring autonomous AI agents integrated with the WhatsApp Business API to automate lead classification, qualification, and context-aware messaging workflows.

## 1. Ambiguity
**The Problem:** The specification for handling incoming webhook payloads from WhatsApp was ambiguous regarding message sequencing. In high-traffic scenarios, users frequently send multiple short, consecutive messages (e.g., "Hi", "I need pricing", "For 5 users"). Handling each message payload as an isolated atomic event led to race conditions, where the AI agent triggered multiple conflicting responses concurrently before the user finished their thought.

**The Resolution:** Since there was no predefined business logic for message chunking, I had to introduce a custom "cooldown/debouncing" window at the backend architecture layer. I designed an asynchronous buffer queue that aggregates incoming messages from the same unique identifier within a dynamic 5-to-10 second window before flattening the payloads into a single contextual prompt for the LLM pipeline.

## 2. Tradeoff
**The Decision:** Choosing between **Prisma ORM** vs. **Raw SQL/Query Builders (like Knex.js)** for database management.

**The Tradeoff:** OmniAI CRM relies on a strictly separated multi-tenant architecture. Prisma provides incredible developer velocity, type-safety across TypeScript models, and elegant relational mapping, which allowed me to build the prototype 0-to-1 rapidly. 
* **The Tradeoff accepted:** I traded runtime execution performance and granular control over raw query execution for schema maintainability. In highly complex relational nested writes (such as deep tracking of multi-stage lead lifecycles), Prisma generates heavy queries that cause a slight overhead compared to optimized raw SQL. For an early-stage SaaS, prioritizing rapid iteration and type safety over raw database micro-benchmarks was the right trade.

## 3. Mistake
**The Error:** Early in development, I executed blocking, synchronous HTTP requests directly within the primary Express/NestJS request-response lifecycle when fetching intent tokens from the OpenAI API and communicating with the WhatsApp API. 

**The Lesson:** During a small stress test, a sudden burst of parallel customer incoming messages choked the Event Loop, causing massive latency spikes and dropped webhooks due to rate-limiting and slow upstream responses from the LLM. 
* **The Fix:** I learned that external network-bound I/O tasks must never block the main runtime thread. I re-architected the system to decouple ingestion from processing, offloading the heavy LLM pipelines and webhook dispatches into an asynchronous job queue with built-in retry mechanisms and backoff strategies.

## 4. Review Comment That Changed My Mind
**The Context:** Initially, I was maintaining stateful user context explicitly within the Python AI scripts by locally caching short-term transaction histories in an in-memory dictionary array to save database roundtrips.

**The Feedback:** During an architectural review, it was pointed out that keeping state bound directly to the runtime environment violates the principles of a stateless, horizontally scalable backend application. If the container or script restarts, or if traffic is distributed across multiple instances, user context completely breaks.
* **The Pivot:** This feedback completely changed my approach to state management. I decoupled the session state entirely from the script execution layer and moved it to a centralized, atomic caching store (Redis), ensuring that the AI execution pipeline remains completely stateless and horizontally scalable under high throughput.