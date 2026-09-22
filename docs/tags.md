# Tags

A tag is a rule, not an opinion. Each one is computed from the table or the chain, each shows its definition on
hover, and each can be argued with.

| Tag | The rule |
|---|---|
{% for k, d in TAGS.items() %}| `{{ k }}` | {{ d }} |
{% endfor %}
This table is generated from the definitions in the code — the same ones the tooltips show, so they cannot drift
apart.

## Three worth reading twice

`no-exits` is the honest one. It does not mean the wallet lost, or still holds. It means we did not buy that data.
Those wallets are counted separately in the summary and never folded into winners or losers.

`transfer-in` means the tokens arrived without a purchase. We see swaps, not transfers, so a wallet that sold more
than it ever bought got them some other way — almost always sent from another wallet.

`seen-before` is the only tag that depends on you rather than the chain. It appears when the wallet was also an
early buyer in **another analysis you saved**, and clicking it opens that list.

!!! info "🔒 Nobody else's analyses are ever part of it"
    Repeats are computed only across the analyses saved to your own account. Nothing leaves the server, and no
    request is spent on it.

## Why there is no score

A score compresses a judgement into a number and then hides the judgement. "Smart money" means whatever the
vendor decided it means, and you cannot check it.

Every tag above can be checked. Open the wallet on Solscan: the first transaction, the funding transfer and the
trade times are right there.
