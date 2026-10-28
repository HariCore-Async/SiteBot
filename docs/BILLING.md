# Billing (scaffolding only)

What exists today, behind `BILLING_ENABLED` (off by default):

- A `plans` table: name, price per month, AI credit per month, bot and embed limits (0 = unlimited), offered or not.
- `users.plan_id`: which plan a user is on (or none).
- Admin console > **Plans** (only when `BILLING_ENABLED=true`): add, edit and delete plans, and a **Plan** column on the
  Users tab to assign one. With the flag off, these screens are hidden and the endpoints answer 404.

What it does **not** do: it charges nothing, talks to no payment provider, and enforces no limit. Usage limits keep
working exactly as before (per-user USD limit, global budget, per-embed daily cap).

## Questions for Hari before real billing

1. **Plans**: which tiers (e.g. Free / Starter / Pro), and what each includes: number of bots, website embeds, pages
   per bot, AI credit or messages per month, team members, headless API access?
2. **Prices and currency**: USD only, or INR too? Monthly only, or yearly with a discount?
3. **Free tier or trial**: a permanent free tier, a trial (how many days, card required?), or neither?
4. **At the limit**: when someone uses up their plan, should the bot stop answering, show an upgrade message to the
   owner only, or allow paid overage?
5. **Who pays**: each user for themselves, or one account paying for a team?
6. **Existing users**: which plan do current users get, and are any grandfathered for free?
7. **Taxes and invoices**: do you need GST invoices (India) or VAT handling? This decides between Stripe Tax and a
   merchant of record such as Paddle or Lemon Squeezy.
8. **Payment account**: do you have (or want) a Stripe account? Stripe in India needs business verification;
   Razorpay is an alternative for Indian cards and UPI.
9. **Refunds and cancellation**: cancel at period end or immediately; any refund policy?

## Proposed implementation once answered (Stripe)

1. Products and prices created in Stripe; each `plans` row stores its Stripe price id.
2. **Upgrade**: Stripe Checkout (hosted page) — SiteBot never sees card details.
3. **Manage / cancel**: Stripe Customer Portal link from Settings.
4. **Webhooks** (`/api/billing/webhook`, signature-checked): `checkout.session.completed`,
   `customer.subscription.updated` / `deleted`, `invoice.payment_failed` keep `users.plan_id` and the subscription
   status in sync.
5. **Enforcement**: plan limits applied where the current usage limits are checked (adding bots and embeds, monthly
   AI credit), with a clear upgrade message to the owner. Visitors on websites never see billing messages.
6. Test end to end in Stripe test mode before switching on live keys.

Needed on Railway at that point: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and `BILLING_ENABLED=true`.
