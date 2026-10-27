# Feature Specification: Reliable Document Upload and Ingestion

**Feature Branch**: `001-reliable-upload-ingestion`

**Created**: 2026-10-27

**Status**: Draft

**Input**: User description: "Create the first Spec Kit feature specification for Reliable Document Upload and Ingestion on the existing production GraphRAG SaaS. Specify a production-grade path for validation, tenant isolation, durable storage, idempotency, asynchronous ingestion, stage-level recovery, retries, dead-letter handling, progress, errors, and safe reprocessing. Reuse the current architecture. Separate confirmed defects from checks that still need a live run. Do not implement or deploy."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Upload a document and know it was accepted (Priority: P1)

A signed-in member chooses a file on the upload screen, optionally types a title, and submits it. The product either rejects the file with a reason the member can act on, or confirms that the original has been stored for that member's organization and that processing has started. Closing the page after confirmation does not lose the document.

**Why this priority**: Members cannot search or ask questions about a document that never lands. Acceptance is the first value this feature must deliver, and it is the step that fails or looks stuck today.

**Independent Test**: Submit one allowed file at the published size limit and one file the product must reject. Confirm the allowed file remains listed for that organization after the page is reloaded, and the rejected file is not stored.

**Acceptance Scenarios**:

1. **Given** a member of an organization and a non-empty allowed file within the published size limit, **When** they submit it, **Then** they see an acceptance confirmation within 30 seconds that includes the document name and that processing has started, and the original remains stored if they leave the page.
2. **Given** the same member submits a second file while the first is still processing, **When** both are within the size limit, **Then** each file is accepted or rejected on its own, and one failure does not discard the other.
3. **Given** a file that is empty, over the size limit, or of a type the product does not accept, **When** the member submits it, **Then** nothing is stored and the screen explains which rule failed.
4. **Given** the member typed a title, **When** the upload is accepted, **Then** the document shows that title. If they left the title blank, the document shows a name taken from the file name.

---

### User Story 2 - Watch processing finish or fail in the open (Priority: P2)

After acceptance, the member sees which step is running, whether a step is being tried again, and a plain-language error if processing stops. The screen does not spin forever when the status check itself fails. A document that is no longer making progress is shown as stalled or failed, not as quietly working.

**Why this priority**: An accepted upload that never becomes searchable is the same outcome as a failed upload, unless the member can see what happened and what to do next.

**Independent Test**: Accept a document, then observe status until it reaches a finished state or a visible failure. Separately, make the status check unavailable and confirm the screen reports that it cannot load progress.

**Acceptance Scenarios**:

1. **Given** an accepted document, **When** processing is underway, **Then** the member sees the current step, how many steps are done, and the latest warning if one exists.
2. **Given** processing stops on a step, **When** the member views that document, **Then** they see the step name, a readable reason, and whether another attempt will be made.
3. **Given** the progress check returns an error or the member is no longer allowed to see the document, **When** the screen refreshes status, **Then** it stops the spinner and shows that error.
4. **Given** processing has not advanced within 2 minutes, **When** the member is still on the status view, **Then** the document is shown as stalled or failed, with the last completed step.

---

### User Story 3 - Recover a document without duplicating it (Priority: P3)

A member or an administrator asks the product to process an already stored document again after a failure, a stall, or a deliberate reprocess. The original file is kept. Searchable copies, graph facts, and extracted assets from the interrupted attempt are not doubled. A document that cannot be recovered is set aside with the reason, and an administrator can see that set and retry it.

**Why this priority**: Recovery is what makes the pipeline safe to operate. It depends on a document that was actually stored, so it follows acceptance and visible status.

**Independent Test**: Store one document, interrupt processing once, then resume or reprocess it. Confirm there is still one original and one current searchable copy, and that a permanently bad item appears on the failed list with a reason.

**Acceptance Scenarios**:

1. **Given** a stored document whose processing stopped mid-way, **When** the product retries, **Then** completed steps are not repeated unless their inputs changed, and the member ends with one document.
2. **Given** a member chooses reprocess on a document they are allowed to manage, **When** reprocess starts, **Then** they see a new run, the previous original remains, and the document returns to an in-progress state they can watch.
3. **Given** a document exhausts retries or hits a permanent problem, **When** an administrator opens the failed-processing list, **Then** the document is listed with the organization, the failed step, the reason, and the time, and a later retry is possible without uploading the file again.
4. **Given** the same file bytes are submitted again for the same organization, **When** the original is still active, **Then** the product does not create a second document and tells the member where the existing one is.

---

### User Story 4 - Keep every document inside its organization (Priority: P4)

A member only uploads into the organization they are signed in to. They cannot see, poll, reprocess, or recover another organization's documents. A document that fails or sits in the failed list is still invisible outside its organization.

**Why this priority**: Isolation is mandatory for this product. It is a separate testable promise from the happy-path upload, and it must hold for failures as well as successes.

**Independent Test**: With two organizations, upload in the first and attempt to view status, reprocess, and list failures as a member of the second. Every attempt is refused, and the second organization sees no trace of the file.

**Acceptance Scenarios**:

1. **Given** a member of organization A, **When** they upload, **Then** the stored file, the processing record, and the status are visible only inside organization A.
2. **Given** a member of organization B who knows organization A's document identifier, **When** they request status or reprocess, **Then** the product refuses and does not reveal the title, the error, or the file.
3. **Given** an administrator of organization A, **When** they open the failed list, **Then** they see only organization A's failures.

---

### Edge Cases

- Empty file, file over the published size limit, and a file whose detected type is not on the allow-list are rejected before a document record is kept.
- The member's connection drops during submit. Either no document is kept, or a stored document is confirmed. The product must not keep a partial original that later processing treats as complete.
- After acceptance, repeating the write URL does not change the final object. The status view still shows the accepted size and etag.
- Two members of the same organization submit the same bytes at the same time. Only one active document is created, and both members receive the same explanation.
- The member submits the same bytes after the earlier document was deleted. The new submission is accepted as a new document.
- Processing stops after the original is stored and before the document is searchable. Retry or reprocess continues from the last completed step and does not store a second original.
- The background processor is down or stuck. New uploads are still accepted only if the original is durable, and status becomes stalled or failed within 2 minutes rather than spinning.
- A step fails for a temporary reason. The product tries again a bounded number of times, then moves the document to the failed list.
- A step fails for a permanent reason, such as an unsupported or unreadable file that passed the first checks. The product does not keep retrying, and the member sees the reason.
- The progress view cannot reach the status service. The screen shows that status is unavailable.
- A remote address is submitted instead of a file. Only safe public addresses are fetched. Private, local, and credentialed addresses are rejected. This path is in scope as a second way to submit a source, and it uses the same acceptance, status, and recovery rules.
- The member has used the organization's upload or storage allowance. The submission is refused with the allowance name and when they can try again, and no original is stored.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The product MUST let a signed-in member submit one file from the existing upload screen and receive either a specific rejection or an acceptance confirmation.
- **FR-002**: Acceptance MUST mean the original bytes are stored for that organization and a processing record exists. A confirmation MUST NOT be shown if either of those is missing. The member-facing confirmation MUST wait for that acceptance. After acceptance, the write URL MUST NOT be able to change those bytes. The accepted original MUST be a protected final object, pinned by size and etag.
- **FR-003**: The product MUST reject empty files, files over the current published maximum of 100 MB, and types outside the current allow-list, before creating a document. A rejected or abandoned intake session MUST leave no document row and no final object.
- **FR-004**: The product MUST detect the file type from the bytes, not from the name alone.
- **FR-005**: The product MUST show the member's title when one was entered, and MUST fall back to the file name only when the title was left blank.
- **FR-006**: The product MUST treat identical bytes inside one organization as one active document. A repeat submission MUST point the member at the existing document. Bytes whose earlier document was deleted MAY be submitted again.
- **FR-007**: The product MUST keep upload, status, reprocess, and the failed list inside the signed-in organization. Missing authorization MUST be a refusal, not an empty success.
- **FR-008**: Processing MUST run after acceptance, off the member's submit request, using the product's existing background processing path. The upload request MUST NOT perform parsing.
- **FR-009**: The product MUST record an ordered series of processing steps for every accepted document, including a visible current step and a finished, failed, skipped, or waiting state for each step.
- **FR-010**: A retry MUST run only for a temporary failure, or for work that can be repeated without creating a second original, searchable copy, or extracted asset. Attempts for one step MUST stop at the existing bound of 3. A permanent failure MUST be dead-lettered with the organization, run, step, and a safe error code, and MUST NOT be retried.
- **FR-011**: A permanent failure, or a temporary failure that has used its attempts, MUST place the document on the failed list with the organization, document, step, safe reason, and time. An authorized member MUST be able to retry that document without uploading the file again.
- **FR-012**: Resume and reprocess MUST skip steps that already completed for the same original and the same processing settings, and MUST replace rather than duplicate searchable content and extracted assets when a step must run again.
- **FR-013**: Status shown to the member MUST include the current step, completed steps, the latest warning, and the error when processing has failed. If status cannot be loaded, the screen MUST say so and MUST stop indicating that work is still running.
- **FR-014**: If a document's processing status has not changed for 2 minutes, the product MUST present it as stalled or failed and MUST include the last completed step in that status.
- **FR-015**: Organization upload and storage allowances MUST be enforced once for the organization, including when more than one upload server is running. A refusal MUST name the allowance and MUST NOT leave a stored original behind.
- **FR-016**: Remote submission MUST accept only safe public addresses, MUST apply the same size and type rules as a file upload, and MUST follow the same acceptance, status, and recovery rules.
- **FR-017**: The member MUST be able to reprocess a document they are allowed to manage. Reprocess MUST keep the stored original and MUST create a visible new processing record.
- **FR-018**: Errors returned to members MUST be safe to read. They MUST NOT include secrets, stored file contents, or another organization's data.
- **FR-019**: The product MUST record who submitted the document and when, for the organization that owns it.
- **FR-020**: This feature MUST reuse the current upload screen, document list, failed-processing list, stored originals, processing steps, and background processor. It MUST NOT introduce a second upload channel or a second processing pipeline.

### Non-Functional Requirements

- **NFR-001**: Under the local Compose journey with one member, MinIO, and no other upload in progress, a file of 100 MB MUST be accepted or rejected within 30 seconds, without the upload screen's process being killed.
- **NFR-002**: Two simultaneous uploads of 100 MB files by the same member MUST each finish the acceptance decision. The upload screen process MUST stay available for a following status request.
- **NFR-003**: After a confirmation, the original and the processing record MUST still exist if the upload screen or the accepting server is restarted.
- **NFR-004**: A single processing interruption MUST NOT leave the organization with two originals or two active searchable copies of the same submission.
- **NFR-005**: Cross-organization access attempts MUST fail closed for upload, status, reprocess, and the failed list.
- **NFR-006**: The background processor MUST be observable as healthy or unhealthy. An unhealthy processor MUST become visible within the same 2-minute window as a stalled document.
- **NFR-007**: Acceptance of a document MUST NOT depend on reading production customer files or production secrets during development or test.

### Key Entities

- **Intake session**: A temporary reservation. It is not a document. It holds the member, the declared size, the staging key, and the expiry. It gains a document only when acceptance commits.
- **Document**: One logical item in an organization, with a title, a type, an owner, a lifecycle state, and at most one active original version. It does not exist for a rejected, expired, or abandoned session.
- **Original**: The final stored bytes for a document version, identified by a content fingerprint, a size, an etag, a detected type, and the organization that owns it. The write URL cannot name this object.
- **Processing run**: One attempt to make a stored original searchable, with a status, a current step, warnings, a safe error, and a link to the document.
- **Processing step**: One ordered unit of work inside a run, with a waiting, running, completed, skipped, or failed state and an attempt count.
- **Failed item**: A run that will not continue on its own, kept for an authorized person to inspect and retry.
- **Allowance**: The organization's remaining document count and stored-byte budget, reserved before storage and released if acceptance fails.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In an automated end-to-end journey, a member completes a successful upload of an allowed file and sees acceptance within 30 seconds, then sees the document on reload.
- **SC-002**: In that same class of journey, a file at the published maximum size is accepted or rejected without the upload screen becoming unavailable.
- **SC-003**: 100% of accepted test documents reach Ready, Failed with a readable reason, or Stalled with the last completed step. None remain in an unchanging "working" state for more than 2 minutes.
- **SC-004**: Resubmitting the same bytes in one organization creates no second active document, and the member is shown the existing document, in 100% of duplicate trials.
- **SC-005**: After one forced processing interruption, the recovered document has one stored original and one active searchable result. A later use of the write URL does not change that original.
- **SC-006**: A member of a second organization cannot view, reprocess, or discover the first organization's document in 100% of cross-organization trials.
- **SC-007**: Empty, oversized, and disallowed-type submissions leave no document behind and show a specific reason in 100% of those trials.
- **SC-008**: An administrator can open one failed item and retry it without a new upload, and the retry is visible as a new run.
- **SC-009**: Automated end-to-end coverage for this feature includes, at minimum, successful upload, rejection, duplicate submission, visible stall or failure, recovery without duplication, and cross-organization refusal. The feature is not releasable while any of those journeys fail.

## Assumptions

- The published maximum upload size stays 100 MB, and the current type allow-list stays as it is. Raising those limits is out of scope.
- Search quality, answer grounding, and model-provider choice are out of scope except where processing must finish far enough for the document to become searchable.
- Members already sign in. This feature does not change how sign-in works.
- "Organization" means the tenant the member is authorized to act in. Document-level access rules already in the product still apply on top of that boundary.
- Remote address submission stays available and must meet the same reliability bar as a file upload. It is not a separate product.
- Safe reprocess and retry replace the current run's unfinished work. They do not keep multiple active versions unless the member explicitly forces a new version. Forced new versions remain an existing capability and are unchanged.
- No new infrastructure product is added. Reliability work fits the current upload screen, document store, background processor, and operator lists.
- Development and automated tests use fixtures and local stand-ins. They do not read production documents or production secrets.

## Findings

### Confirmed from the current product

These behaviors are visible in the product definition and do not depend on a live run. They are defects or gaps this feature must close. They are not, by themselves, proof of which one a given member hit last.

- The upload screen receives the whole file and forwards another copy before the document is stored. The screen's memory budget is 512 MB for the whole application, while the product allows a 100 MB file. One large upload, or two at once, can exhaust that budget and end the submission before acceptance. The service that stores the file has a larger budget, so the loss happens on the screen's hop.
- The processor is explicitly told to take work from the shared queue. The accepting service is not given that same instruction and instead infers the queue. If the queue cannot be opened, the error is discarded and the job is held only in that accepting process. A restart drops it, and the processor never sees it. The member can still be told the document was accepted.
- The processor runs as a single copy and publishes no health signal. The accepting service runs as two copies and does publish health. A dead processor does not fail the platform's own health, so new documents can be stored and then never move.
- If the progress request fails, the upload screen ignores the failure and keeps showing that work is in progress.
- When a file name is present, the title typed on the upload screen is discarded and the document is named from the file name.
- Upload and storage allowances are counted in each accepting process separately, so two accepting servers do not enforce one organization budget.
- Validation, content fingerprints, duplicate refusal, organization-scoped storage, ordered processing steps, bounded retries, a failed-item record, and status fields already exist. This feature repairs the path around them. It does not replace them.
- Recovery behavior is covered by automated checks that use stand-in storage and a stand-in queue. Those checks do not prove the deployed screen, the deployed processor, and the deployed stores together.

### Requires a live check

No production system, production secret, or production document was inspected. No local runtime log of a failed upload was available in the workspace. Until the checks below are done in a non-production environment, the feature must not treat one defect as the sole cause.

- Whether recent member-visible failures are a killed upload screen, an acceptance followed by no progress, a stored processing error, or a validation rejection.
- Whether the shared queue address used by the accepting service and the processor is actually reachable. A bad address that fails while sending, rather than while creating the client, stays on the durable to-do list and can be sent again. That is a different failure from the discarded client error above.
- Whether the running processor includes every document reader the pipeline expects. The processor build is allowed to succeed with a smaller set of readers if the full set does not install.
- Whether documents currently sit in "ingesting" with no recent sign of life, or are already on the failed list with a step reason.
- Whether the deployed maximum size still matches the 100 MB product default.
