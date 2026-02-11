PYTHON ?= python3
ROOT_DIR := $(CURDIR)
FIXTURE_CONTRACTS := tests/fixtures/contracts
FIXTURE_SLITHER := tests/fixtures/slither.json
DIFF_REPO := tests/fixtures/diff_repo

.PHONY: demo clean-artifacts diff-fixture

clean-artifacts:
	rm -rf artifacts
	mkdir -p artifacts

diff-fixture:
	@if [ ! -d "$(DIFF_REPO)/.git" ]; then \
		mkdir -p $(DIFF_REPO)/contracts; \
		git -C $(DIFF_REPO) init; \
		git -C $(DIFF_REPO) config user.email "demo@example.com"; \
		git -C $(DIFF_REPO) config user.name "Demo User"; \
		printf "pragma solidity ^0.8.13;\ncontract Vault { function withdraw() public {} }\n" > $(DIFF_REPO)/contracts/Vault.sol; \
		git -C $(DIFF_REPO) add contracts/Vault.sol; \
		git -C $(DIFF_REPO) commit -m "base"; \
		printf "pragma solidity ^0.8.13;\ncontract Vault { function withdraw() public { (bool ok,) = address(0).call(\"\"); ok; } }\n" > $(DIFF_REPO)/contracts/Vault.sol; \
		git -C $(DIFF_REPO) add contracts/Vault.sol; \
		git -C $(DIFF_REPO) commit -m "head"; \
	fi

demo: clean-artifacts diff-fixture
	cp $(FIXTURE_SLITHER) artifacts/slither.json
	printf '{\n  "budget": { "cap": 1, "spent": 1 },\n  "capabilities": { "executed": [], "skipped": [] }\n}\n' > state.json
	PYTHONPATH=$(ROOT_DIR) RALPH_OFFLINE=1 $(PYTHON) -m ralph_wiggum.cli audit $(FIXTURE_CONTRACTS)
	PYTHONPATH=$(ROOT_DIR) RALPH_OFFLINE=1 $(PYTHON) -m ralph_wiggum.cli workbench $(FIXTURE_CONTRACTS)
	PYTHONPATH=$(ROOT_DIR) RALPH_OFFLINE=1 $(PYTHON) -m ralph_wiggum.cli entrypoints $(FIXTURE_CONTRACTS)
	BASE_REF=$$(git -C $(DIFF_REPO) rev-list --max-parents=0 HEAD); \
	HEAD_REF=$$(git -C $(DIFF_REPO) rev-parse HEAD); \
	(cd $(DIFF_REPO) && PYTHONPATH=$(ROOT_DIR) RALPH_OFFLINE=1 $(PYTHON) -m ralph_wiggum.cli diff $$BASE_REF $$HEAD_REF --target contracts)
