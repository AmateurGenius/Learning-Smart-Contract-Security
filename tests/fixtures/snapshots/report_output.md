# Ralph Wiggum Audit Report

## Findings
- reentrancy: 1
- unchecked_return: 0
- delegatecall: 0

## Evidence
- reentrancy at contracts/Vault.sol

## Recommendations
- Review reentrancy guards and external call ordering.

## Ranked Findings
| Rank | Score | Severity | Confidence | Tool | Category | Description |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 9 | high | high | slither | reentrancy | Reentrancy in withdraw |
| 2 | 7 | medium | medium | foundry | fuzz | Fuzz failure in testWithdraw |

## Capabilities Executed / Skipped
- Executed: static_scan (fixture)
- Skipped: None

## LLM Synthesis
_This section is heuristic synthesis, not evidence._
- LLM synthesis unavailable.
