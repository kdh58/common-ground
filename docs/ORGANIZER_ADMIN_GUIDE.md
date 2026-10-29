# Common Ground

## Organizer and Administrator Guide

*Version 1.0 — October 2026*

### Purpose

Common Ground provides tools for organizing community gatherings, managing participation, collecting questions, and preparing discussion themes.

The organizer retains control over the gathering and all published discussion content. Artificial intelligence assists with preparation; it does not independently make decisions for the community.

## 1. Access the Host Workspace

Open `/host` on the Common Ground website and sign in using the authorized host password.

The host dashboard provides access to gathering management and administrative functions.

The current prototype uses shared-password authorization rather than separate named user accounts. Host credentials should only be shared with authorized administrators.

## 2. Create and Manage a Gathering

Create a gathering and enter its identifying information, description, schedule, and location or participation details.

From the host dashboard, choose Manage Gathering to work with an existing gathering.

The gathering workspace organizes its functions into three principal areas:

- Gathering: details, agenda, resources, and status
- Participants: registrations and submitted questions
- Discussion Themes: AI-generated suggestions, manual themes, and published discussion material
Existing gathering details can be revised as planning progresses.

A gathering can be canceled and subsequently restored without deleting its participant submissions.

## 3. Prepare the Agenda and Resources

Within the Gathering section, add agenda items and arrange them in the intended discussion order.

Edit or remove items as plans change.

Add supporting resources by providing relevant URLs. These might link to background documents, public information, or other materials participants should review.

The current implementation supports linked resources rather than direct file uploads.

Review the public gathering page to confirm that information and resources appear as intended.

## 4. Manage Participation

Open the Participants section to review registrations and submitted questions or ideas.

Registration and question submission are independent activities. RSVPs collect only a name or nickname, and questions are not linked to RSVP records. A question may come from someone who has not registered to attend.

For administrative use, export the information as separate CSV files:

- Registration export: attendee-related information
- Question export: submitted questions and ideas
Treat these exports as private organizer records. The current forms do not collect participant email addresses or telephone numbers.

Do not assume that material available to the host is automatically appropriate for publication.

## 5. Generate Discussion Themes with AI

Open the Discussion Themes area for the relevant gathering.

Select Suggest Discussion Themes to request analysis of that gathering's submitted questions.

The application sends the relevant material to the configured Ollama model and generates suggested discussion themes.

The process may take some time, depending on model and network availability.

AI output is created as a private draft. It does not automatically become publicly visible.

Each analysis run is retained separately, allowing organizers to review and compare results without silently replacing previous work.

Suggested material can include:

- Theme title and description
- Shared concerns
- Different perspectives
- Suggested discussion questions
- References to the original participant submissions
These are model-generated interpretations that require human review.

## 6. Review, Revise, and Publish Themes

Inspect each suggested theme before approving it.

Edit titles, descriptions, and discussion questions as needed. Add organizer notes or create additional themes manually.

Review whether the generated analysis accurately reflects the contributions it references.

The organizer controls the progression from private draft through approval to publication.

Only explicitly published theme titles and descriptions appear on the participant page. Approval alone does not publish them. Editing an approved or published title or description returns the theme to draft and removes it from the participant page. Facilitation notes, including suggested discussion questions, remain private to the host.

Published themes can be unpublished without deleting them.

The system also supports managing analysis runs, including deactivating, reactivating, and deleting eligible runs. Deletion is restricted when approved, published, or manually created themes must be preserved.

## 7. Inspect and Print an Analysis

Use View / Print Analysis to inspect the generated analysis in a separate protected view.

The report provides discussion-theme information, references to source questions, and coverage information to help the organizer evaluate the analysis.

Use the available print or download controls to prepare materials for facilitation.

Access remains restricted to authorized hosts.

## 8. Handling AI Unavailability

AI-assisted features depend on the configured Ollama service being reachable from the application. The service may run locally or on an allowed private-network endpoint.

If AI analysis is unavailable, use the application's displayed status and retry guidance. Verify availability before attempting another analysis.

The rest of the gathering workflow—registration, submission, agenda preparation, and administration—is designed to remain usable without AI inference.

An organizer can prepare discussion themes manually.

## 9. Privacy and Responsible Operation

Use participant information only for legitimate gathering purposes.

Preserve original contributions even when AI produces condensed interpretations.

Check generated themes for omissions, misleading generalizations, and misrepresentations.

Keep administrator credentials and exported files secure.

Common Ground is a demonstration prototype. Organizations intending to use it with real participants should review their privacy, retention, access-control, accessibility, and operational requirements before deployment.

## 10. Operating Principle

Common Ground is most useful when it helps an organizer prepare a conversation without taking ownership of the conversation away from its participants.

Use the technology to inform human judgment, never to replace it.
