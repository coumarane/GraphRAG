# Feature Specification: RAG Reliability and Retrieval Quality

**Feature Branch**: `cursor/002-rag-reliability-and-retrieval-quality-7784`

**Created**: 2026-11-02

**Status**: Draft

**Input**: User description: "Create Spec Kit feature 002-rag-reliability-and-retrieval-quality. Feature 001 is accepted on DEV. Do not redesign or reimplement its upload architecture. Focus on worker liveness under CPU-intensive parsing, page-level citation provenance for parent and child chunks, retrieval relevance and no-evidence behavior, Neo4j indexing versus graph traversal, skipped optional stages versus genuine warnings, reproducible browser end-to-end tests against DEV, and CI/CD acceptance plus deployed/rollback digest consistency. Use the existing architecture. Do not modify the running DEV deployment until this feature is reviewed."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Parsing stays up (Priority: P1)

A member submits a document that needs heavy reading. Processing continues, and the worker that is doing the reading still answers its health check. A busy document does not restart the worker. A worker that has actually stopped is still reported unhealthy.

**Why this priority**: Feature 001 accepted the upload and the isolated parser. On 2 November 2026 the DEV worker restarted once at 11:44 Europe/Paris because its liveness check timed out, and Kubernetes recorded that restart as a clean completion. Later uploads on the same process succeeded. A health check that cannot be answered during real work will keep restarting a healthy worker.

**Independent Test**: Start one worker, submit three documents that each hold the parser, and confirm the same worker process answers its liveness check within 5 seconds throughout. Stop the process and confirm it is reported unhealthy.

**Acceptance Scenarios**:

1. **Given** a worker that is parsing one document, **When** its liveness check runs, **Then** the check succeeds within 5 seconds and the parse continues on the same process.
2. **Given** three documents parsed one after another, **When** each parse is CPU-heavy, **Then** the worker restart count does not increase because of those parses.
3. **Given** the worker process has exited, **When** the platform health check runs, **Then** the worker is unhealthy.
4. **Given** an operator stops the worker on purpose, **When** the process leaves, **Then** that stop is distinguishable from a liveness timeout during a healthy parse.

---

### User Story 2 - A citation names the page it quotes (Priority: P1)

A member asks about a sentence that appears on one page of a multipage document. The citation names a page range that contains that sentence. A parent passage that spans several pages is not relabeled as the first page. A child passage keeps the page it was built from. Search evidence and the answer citation for the same passage agree.

**Why this priority**: Feature 001 stored correct per-page chunks for a four-page cosmetics PDF. The answer citation for a page-2 sentence was also labeled pages 1–1 while the quoted text was the page-2 sentence. The parent passage spanned pages 1–4. Members cannot trust a page number that the quoted text does not occupy.

**Independent Test**: Index one generated four-page PDF whose pages contain distinct sentences. Retrieve each sentence and compare the citation page range with the page that contains it.

**Acceptance Scenarios**:

1. **Given** a phrase that exists only on page 2, **When** the member searches or asks for it inside that document, **Then** at least one citation includes page 2 and the quoted text contains the phrase.
2. **Given** the same phrase is also present in a parent passage spanning pages 1–4, **When** that parent is cited, **Then** its page range still covers page 2 and is not reduced to page 1 alone.
3. **Given** a child passage built from page 4 only, **When** it is cited, **Then** its page range is page 4.
4. **Given** the same passage is returned by search and by the answer, **When** both are shown, **Then** they name the same document and the same page range.

---

### User Story 3 - An unsupported question returns no evidence (Priority: P1)

A member limits a question to one document. If that document does not support the question, the product returns no evidence and no citation, and it says the selected document did not support the question. It does not fill the answer with the nearest passage from that document. The same question limited to the document that does contain the fact returns only that document. Another organization sees neither document.

**Why this priority**: On the accepted DEV run, a serum sentence searched inside the toner document returned the toner passage with the sentence absent. Search currently returns the nearest passages inside the selected documents. The answer path has a sufficiency check, and search does not use it. A weak hit is shown as support.

**Independent Test**: Using two documents in one organization and a third organization with no access, search a distinctive sentence once inside the document that lacks it and once inside the document that contains it.

**Acceptance Scenarios**:

1. **Given** a distinctive phrase that is absent from the selected document, **When** the member searches or asks inside that document only, **Then** the evidence list and the citation list are empty and the response says the selected document did not support the question.
2. **Given** the same phrase in the document that contains it, **When** the member selects only that document, **Then** every evidence item and citation belongs to that document and at least one contains the phrase.
3. **Given** a member of another organization, **When** they search either document, **Then** they receive no evidence, no citation, and no graph path from the first organization.
4. **Given** one low-scoring passage is the only candidate, **When** its retrieval score is below the sufficiency floor, **Then** rescaling that single score does not make it sufficient.

---

### User Story 4 - A stored graph can be walked (Priority: P2)

After processing, the member can ask for the graph paths behind an answer. If the product stored a graph for that document, the response either returns a path inside that document or gives a reason no path was walked. A finished graph step with an empty path and no reason is not a successful graph answer. Paths stay inside the member's organization.

**Why this priority**: Feature 001 completed graph indexing for the cosmetics PDF and returned zero graph paths. The stored graph can be a structural map of the document and its passages, or a semantic map of entities. Retrieval walks entity names. A structural map with no matching entity becomes an empty path even though indexing finished. Operators cannot tell "nothing was stored" from "nothing was walked."

**Independent Test**: Index one document, confirm the graph step finished, request paths, and require either an in-document path or an explicit reason.

**Acceptance Scenarios**:

1. **Given** graph indexing finished for a document, **When** the member requests graph paths for a question about that document, **Then** the response includes a path whose nodes belong to that document or a reason that no path was walked.
2. **Given** the stored graph is only the document, its version, and its passages, **When** paths are requested, **Then** a structural path among those nodes is a valid path.
3. **Given** entity relationships were stored, **When** the question names one of those entities, **Then** the path may follow those relationships and still stays inside the selected document and organization.
4. **Given** a member of another organization, **When** they request paths, **Then** no node from the first organization is returned.

---

### User Story 5 - Optional skips are not warnings (Priority: P2)

A member or operator reading a finished run can tell an optional step that was intentionally left idle from a step that failed part of its work. A run whose only idle steps are the optional ones finishes clean. A genuine enrichment failure is visible as a warning on that step and as the run's latest warning. The document's partial state remains the needs-review outcome.

**Why this priority**: Feature 001's three accepted documents finished `completed_with_warnings` with the latest warning "community summarization disabled." Those steps were skipped on purpose. The stage list already showed `skipped`. The run status and the latest warning treated the skip reason as a failure.

**Independent Test**: Finish one run that only skips optional steps, and one run that records a genuine enrichment failure, and compare status, latest warning, and stage status.

**Acceptance Scenarios**:

1. **Given** a run that completes every required step and skips only optional steps, **When** the member reads the run, **Then** the run status is completed and the latest warning is empty.
2. **Given** an optional step that was not requested or is disabled, **When** it is skipped, **Then** its stage status is skipped and its reason stays on that stage.
3. **Given** a genuine enrichment or parse failure, **When** the run finishes, **Then** the run status is completed with warnings and the latest warning is that failure, not an optional skip reason.
4. **Given** a document that needs review because parsing or vision was incomplete, **When** the member reads the document, **Then** its status is partial, which is a different outcome from a skipped optional step.

---

### User Story 6 - The browser journey can be repeated against DEV (Priority: P2)

A reviewer can run one browser journey against the DEV site. It signs in, uploads a generated multipage PDF, waits until the document is ready, and shows a page citation for that document only. The journey uses a normal PDF, not a hand-assembled file. Missing address or credentials fail the run. The run does not print secrets and does not pass by skipping the browser.

**Why this priority**: The current browser tests target a local site, use local demo credentials when none are supplied, and upload a hand-built one-page PDF. A GitHub-hosted runner that calls the public API is rejected before login. Feature 001's accepted page checks ran inside the cluster, not in the browser. The hand-built PDF also produced the wrong page map.

**Independent Test**: With the DEV web address and credentials supplied outside the repository, run the browser journey once and keep its trace. Run it again with the address removed and confirm it fails.

**Acceptance Scenarios**:

1. **Given** the DEV web address and member credentials, **When** the browser journey runs, **Then** a generated multipage PDF is uploaded, becomes ready, and a question about one page shows that page and that document.
2. **Given** a second document uploaded in the same journey, **When** the question is limited to the first document, **Then** the other document is not cited.
3. **Given** the address or the credentials are absent, **When** the journey is started against DEV, **Then** it fails before upload and does not fall back to a local demo member.
4. **Given** the runner cannot open the DEV site, **When** the job ends, **Then** the job fails and records that the site could not be opened. It does not report success from an in-cluster API call alone.

---

### User Story 7 - Acceptance and rollback identities agree (Priority: P2)

An operator can read two identities for each deployed part: the image that is serving, and the image that a rollback would restore. A promotion changes the serving image and leaves the rollback image in place. The acceptance job ends with the same result as the product checks. A script error after a successful check does not hide a failure, and a successful check is not reported as a product failure.

**Why this priority**: The serving images and the rollback images differ, which is what a rollback target requires. The test that guards the release gate checks only the rollback file. Older rollout text treated those rollback images as the images Argo CD was running. The acceptance job on 2 November 2026 printed success and then failed because a script closer did not match its opener.

**Independent Test**: Read the serving identities and the rollback identities from the repository. Promote nothing. Confirm they are both present, the promotion switches are closed, and a broken acceptance-script fixture fails a local check.

**Acceptance Scenarios**:

1. **Given** the release record after Feature 001, **When** an operator compares serving and rollback identities, **Then** both are present and they are not stored as the same set.
2. **Given** a promotion of one part, **When** the serving identity changes, **Then** the rollback identity for that part remains the previous serving identity.
3. **Given** an explicit rollback, **When** the serving identity is restored, **Then** the record says a rollback is in effect and the serving identity matches the rollback identity.
4. **Given** product checks that passed, **When** the acceptance job finishes, **Then** the job result is success. **Given** product checks that failed, **When** the job finishes, **Then** the job result is failure.

### Edge Cases

- The liveness check and a long parse happen together. The check still returns. Readiness may still fail when a dependency is down.
- A parent passage and a child passage contain the same sentence. Each citation uses its own page range, and neither range drops the page that contains the sentence.
- The selected document contains the phrase on a page the parser merged into a neighbor page. The citation follows the stored page of the passage that contains the phrase. A hand-built PDF is not the fixture used to judge that.
- The question has no distinctive token and every score is low. The response is no evidence rather than the first passage in the document.
- Graph indexing was skipped because the graph store was disabled. The response reason says the graph was not stored. It does not say a path was walked.
- Two optional skips and one genuine warning occur in the same run. The latest warning is the genuine warning.
- The browser runner is refused by the edge in front of the public API. The browser job fails. The in-cluster upload check from Feature 001 remains available and is not renamed as the browser result.
- A workflow file on the default branch is the file a repository dispatch executes. A fix to that file is a workflow-only change and does not build or promote an image.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The worker MUST answer its liveness check within 5 seconds while a document is parsing. The check MUST NOT wait on the ingestion lock or on the parse.
- **FR-002**: Three consecutive CPU-heavy parses MUST leave the worker process in place. A process that has exited MUST be unhealthy.
- **FR-003**: An intentional worker stop MUST remain a clean stop. A liveness timeout during a healthy parse MUST NOT be required for the worker to stay in service.
- **FR-004**: Feature 001's upload session, direct object write, completion, duplicate detection, and isolated parser child MUST stay in place. This feature MUST NOT add a second upload path or a second queue.
- **FR-005**: A citation MUST name a page range that contains the quoted passage. Search evidence and the answer citation for the same passage MUST name the same document and the same page range.
- **FR-006**: A parent passage that spans more than one page MUST keep a range that covers the quoted page. The product MUST NOT rewrite that range to the first page alone.
- **FR-007**: A child passage MUST keep the page range of the elements it was built from.
- **FR-008**: Search and answer MUST apply the same evidence floor. A passage below that floor MUST NOT be returned as evidence or as a citation.
- **FR-009**: When the question contains a distinctive phrase that is absent from every passage in the selected documents, search and answer MUST return no evidence and no citation and MUST say that the selected documents did not support the question.
- **FR-010**: Rescaling the scores of a single candidate list MUST NOT turn a below-floor passage into a sufficient passage.
- **FR-011**: Evidence, citations, and graph paths MUST stay inside the caller's organization and inside the selected documents. A caller outside that organization MUST receive none of them.
- **FR-012**: A request for graph paths after a finished graph step MUST return either a path inside the selected document or a reason no path was walked. An empty path with no reason MUST NOT be treated as proof that the graph was used.
- **FR-013**: A stored structural map of the document and its passages MUST be a valid path when no entity relationship is available. Entity relationships MUST remain available when they were stored.
- **FR-014**: A skipped optional step MUST keep stage status skipped and MUST NOT by itself set the run status to completed with warnings or set the latest warning.
- **FR-015**: A genuine enrichment or parse failure MUST set the run to completed with warnings, MUST be visible on the failing step, and MUST be the latest warning in preference to any skip reason. Document status partial MUST remain the needs-review outcome.
- **FR-016**: Optional steps that stay idle on the accepted path are table enrichment, equation enrichment, context build, unrequested document intelligence, entity resolution, and community summarization. This feature MUST NOT enable community summarization in order to clear the warning.
- **FR-017**: One browser journey MUST be runnable against the DEV web origin with credentials supplied outside the repository. It MUST upload a generated multipage PDF, wait until ready, and show a page-level citation for that document only.
- **FR-018**: The DEV browser journey MUST fail when the origin or the credentials are missing, MUST NOT fall back to a built-in demo member, MUST NOT print secrets, and MUST NOT report success when the browser could not open the site.
- **FR-019**: The acceptance job result MUST be the product-check result. Serving image identities and rollback image identities MUST both be recorded. A promotion MUST change the serving identity and MUST leave the previous serving identity as the rollback identity. An explicit rollback MUST say that a rollback is in effect.
- **FR-020**: This feature MUST reuse the current API, the Redis-backed worker, Qdrant, Neo4j, the Next.js application, and the OVH Kubernetes delivery path. It MUST NOT add a second worker framework. The admin console already records that Celery is unused.

### Non-Functional Requirements

- **NFR-001**: Liveness answers within 5 seconds during a parse that is otherwise healthy. Readiness still reports dependency failure.
- **NFR-002**: Page citations for the four-page fixture are exact for pages 2, 3, and 4 in every automated trial of that fixture.
- **NFR-003**: No-evidence and cross-organization trials fail closed in 100% of automated trials.
- **NFR-004**: Automated tests use generated PDFs and local stand-ins. They do not read production documents or production secrets.
- **NFR-005**: No database schema change is required for the warning rule, the page rule, or the evidence floor. A new Alembic revision is out of scope unless a later review finds a stored field that cannot represent the reason codes.

### Key Entities

- **Worker health**: The liveness answer, the readiness answer, the process start time, and the restart count. Liveness is independent of the document being parsed.
- **Passage**: A parent or child chunk with text, document, version, and a page range. The page range is the provenance of that text.
- **Citation**: The page range, document, and quoted text shown for one passage. It matches the passage it quotes.
- **Evidence floor**: The lowest retrieval score that still counts as support. A single-item rescaling is not a score.
- **Graph path**: An ordered set of nodes and relationships inside one organization and, when documents were selected, inside those documents. It has a kind of structural or entity, or it is absent with a reason.
- **Step outcome**: Completed, skipped, or completed with a genuine warning. The run status is derived from genuine warnings only.
- **Release identity**: The serving image digest and the rollback image digest for the API, the worker, and the web application, plus whether a rollback is in effect.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In an automated worker trial, liveness answers within 5 seconds during each of three CPU-heavy parses, and the restart count is unchanged. After the process exits, the health check fails.
- **SC-002**: On the four-page fixture, a query for the sentence that exists only on page 2, page 3, or page 4 returns a citation whose range includes that page and whose quoted text contains the sentence, in 100% of trials. No citation reports only page 1 for a sentence that is absent from page 1.
- **SC-003**: A distinctive sentence searched inside a document that lacks it returns an empty evidence list, an empty citation list, and an unsupported-selection message, in 100% of trials. The same sentence inside the document that contains it returns only that document. A second organization receives none of those passages.
- **SC-004**: After graph indexing finishes, a path request returns either an in-document path or a non-empty reason, in 100% of trials. Paths from another organization are absent.
- **SC-005**: A run with only optional skips has status completed and an empty latest warning. A run with one genuine enrichment failure has status completed with warnings and that failure as the latest warning, in 100% of classification trials.
- **SC-006**: One documented browser command against DEV uploads a generated multipage PDF and shows a page citation for that document only. The same command fails when the DEV address or credentials are omitted.
- **SC-007**: The acceptance job conclusion matches the product checks in a local fixture of both a passing and a failing check. Serving and rollback identities are both asserted, and a promotion fixture leaves the rollback identity unchanged.
- **SC-008**: The feature is not releasable while any of SC-001 through SC-007 fail. Releasing it requires a reviewed change on the existing delivery path. This specification does not deploy it.

## Assumptions

- Feature 001 remains the upload, isolation, and ingestion path. Its accepted DEV digests stay in service until this feature is reviewed and deliberately promoted.
- The worker remains one replica. The queue remains the Redis stream already used by that worker.
- The evidence floor stays the existing sufficiency floor of 0.12 on the retrieval score. This feature applies that floor to search and stops single-list rescaling from replacing it. Raising or lowering the floor is a measured evaluation change, not part of the first correction.
- Community summarization, unrequested document intelligence, table enrichment, equation enrichment, context build, and entity resolution stay optional and idle on the ordinary PDF path.
- Parser library versions stay as they are. A liveness fix MUST NOT depend on upgrading PDFium, Torch, or Marker.
- The DEV browser journey runs from a network that can open the DEV web origin. A hosted runner that is refused by the edge fails the job. Credentials stay in the existing secret store.
- Repository dispatch reads workflow files from the default branch. A workflow-only correction there does not promote an image and does not merge this feature into the default branch.
- No new database, queue, or cluster add-on is added.

## Findings

### Confirmed from the current product

These are visible in the product and in the Feature 001 DEV acceptance on 2 November 2026. They are the gaps this feature closes.

- The worker liveness check is answered by the same process that is busy parsing, and it can time out during that work. The check waits 5 seconds and repeats every 15 seconds. A timeout restarts the worker. The process treats that stop as a clean exit, so the restart is recorded as completed with exit 0. One such restart happened at 11:44 Europe/Paris, before the three acceptance uploads. Those uploads did not restart the worker again.
- Parent passages record the first and last page of their elements. Child passages record their own elements' pages. When a citation is built, a range of three or more pages is rewritten so the end page equals the start page. A parent spanning pages 1–4 becomes a citation of page 1. The DEV page-2 query showed that citation while the quoted text was the page-2 sentence. Search evidence for the same passage still said pages 2–2.
- Search returns the nearest passages inside the selected documents and does not apply the sufficiency floor. The answer path classifies a top score below 0.12 as insufficient, and it blocks only when the evidence list is already empty. The toner search for the serum sentence returned the toner. Min-max rescaling of a one-item list becomes 1.0 and is stored beside the score; the decision must keep using the retrieval score.
- Graph indexing can store a structural map or a semantic entity map, and the step still completes when semantic extraction fails over to the structural map. Path retrieval looks up entity names and otherwise returns no path. The accepted searches asked for paths and received none, with graph indexing completed and no semantic failure marker.
- A skip stores its reason in the same field as a warning. Any such text makes the run completed with warnings, and the latest warning is the last of those texts. On the accepted runs that text was "community summarization disabled." The stage status was skipped. Genuine markers already used by the acceptance check are `semantic_graph_failed`, `vision_failed`, `needs_review`, `parser_fallback`, and `parser_routing`.
- Browser coverage is local. The DEV page proof was an in-cluster API script. A hand-built PDF made Docling assign the last page incorrectly. A generated PDF assigned pages 1, 2, 3, and 4 correctly.
- The release gate stores rollback digests and keeps promotion switches closed. The serving digests live in the Kubernetes kustomization and are different. The unit test checks the gate file only. The acceptance job printed a passing product result and then exited because a Python block was closed with the wrong token.

### Requires a review before any deploy

This specification does not change the running DEV deployment. Until the feature is reviewed, the serving digests stay the Feature 001 images recorded in `specs/001-reliable-upload-ingestion/acceptance.md`.

- Whether the 11:44 Europe/Paris restart was the event loop blocked by parsing, or a readiness dependency that only surfaced on the shared loop. The required behavior is the same: liveness answers during a healthy parse.
- Whether the serum sentence's retrieval score was below 0.12. The required behavior does not depend on that sample: absence of the distinctive phrase from the selected document is no evidence.
- Whether the stored cosmetics graph contains entity nodes or only structural nodes. The required behavior covers both: return the path that exists, or the reason none was walked.
