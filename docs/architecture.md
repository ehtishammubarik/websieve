# Architecture

## Why the stages are in this order

Each stage costs more than the one before it, so each exists partly to shrink
the input to the next.

```
extract -> normalize -> exact dedup -> quality -> near dedup -> embed
 parse       regex        1 hash       9 rules    n hashes     model
```

| Boundary | Reason |
| :--- | :--- |
| normalize before any comparison | Two byte encodings of one character defeat both hashing and the ratio thresholds |
| exact dedup before quality | One hash beats nine heuristics, and typically removes a large share of a crawl |
| quality before near dedup | A MinHash signature costs `num_perm` hashes per shingle. Signing a document you are about to drop is pure waste |
| embed last | Orders of magnitude more expensive than everything above it combined |

Reordering is possible but has a cost. Running quality before exact dedup, for
instance, means running nine heuristics against documents a single hash would
have removed.

## Memory

The pipeline is a generator. Memory grows with documents *kept*, not documents
*seen*, because the only retained state is the dedup index:

- `ExactDeduper` holds one 16-byte digest plus one key per unique document.
- `LSHIndex` holds a `num_perm`-length signature per kept document, plus
  `bands` bucket entries pointing at it.

The full retained size is not the digest bytes alone: CPython objects, keys,
tuples, integers, dictionaries, and bucket lists all add overhead. In the
[reproducible benchmark](benchmarks.md), fresh processes peaked at 42 MiB for
1,000 input documents, 86 MiB for 5,000, and 140 MiB for 10,000. Those points
fit a 31.5 MiB baseline plus 10.8 MiB per 1,000 inputs. Because the exact and LSH
indexes retain keys and MinHash signatures for every kept document, memory
growth is linear: the fitted RSS consumes 16 GiB around 1.5 million inputs, 32
GiB around 3.0 million, and 64 GiB around 6.1 million. Practical ceilings are
lower because the process cannot safely consume all installed RAM.

This makes memory the binding constraint before throughput at scale and gives
concrete motivation to both a [persistent index](https://github.com/ehtishammubarik/websieve/issues/5)
and [parallel, partitioned processing](https://github.com/ehtishammubarik/websieve/issues/15).
The fit extrapolates beyond a controlled 1,000–10,000-document range; rerun the
benchmark at representative document lengths, duplicate rates, and settings
before sizing a production job.

Partitioning by URL host bounds each in-memory index and parallelizes cleanly,
but it necessarily misses duplicates copied across hosts. Whether that recall
trade is acceptable must be measured on the target corpus.

## Why no dependencies

Not minimalism for its own sake. This code runs in three places where
dependencies are genuinely expensive:

1. **Inside a scraper container** you do not control, where adding `numpy`
   means rebuilding someone else's image.
2. **Air-gapped environments**, where every wheel is a procurement conversation.
3. **CI**, where a dependency-free core installs in under a second.

The cost is measured rather than compared to an implementation this repository
does not ship. On the benchmark's controlled 160-word documents, MinHash
processed 696 documents/s at 64 permutations, 360 at 128, and 182 at 256.
Accuracy moved with that cost: 64 permutations missed 4 of 200 known
duplicates, while 128 and 256 missed none. See [the benchmark](benchmarks.md)
for the exact source, hardware, and limits.

The CI job that fails on any acquired runtime dependency exists because this
claim rots the first time someone adds a convenient import, and it would pass
tests in a fatter dev environment.

## Extension points

| To change | Implement |
| :--- | :--- |
| Extraction | Anything returning `(text, title)`; swap it in `Pipeline.process` |
| Quality rules | A `Callable[[str], Rule]`, then pass a custom tuple to `assess` |
| Embedding model | The `Encoder` protocol: one `encode(texts) -> list[list[float]]` |
| Output format | Mirror `JsonlShardWriter`: `write`, `close`, and a manifest |

## Known limitations

Stated plainly, because a limitation you find yourself is worse than one you
were told about.

- **Extraction is a heuristic.** It will lose content on pages whose body is
  fragmented across many short blocks, and keep a sidebar that happens to be
  long and prose-like. Use `trafilatura` when accuracy matters more than
  portability.
- **Script is detected, language is not.** The rule set adapts to the writing
  system, which is what the thresholds actually depend on. It will not tell you
  Mandarin from Cantonese, or Hindi from Marathi, because that needs a model and
  no threshold here varies on it.
- **Dedup is greedy and order-dependent.** The first document in a cluster
  wins. Feeding the corpus in a different order can keep a different
  representative.
- **`structural` exact hashing merges numeric-only differences** by design.
  Wrong for price tracking, right for training corpora.
- **The LSH index is in-process.** No persistence, no sharing between workers.
