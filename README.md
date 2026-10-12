# studai-sample

Two files from the backend of StudAI, a math tutor for Hungarian students I'm building. The main repo is private, so this won't run on its own. It's here to show how a tutor turn is put together.

The short version: the LLM doesn't decide anything about the math. It only writes the text. Before that, the student's problem gets compiled into a typed form (I call it MathIR), a deterministic verifier and solver check the student's step, and the system keeps track of the student's state (help level, errors, misconceptions). From that it picks a teaching move from a fixed list, like ASK_NEXT_STEP or ASK_JUSTIFICATION.

## What's in here

`action_validator.py` checks the chosen move against the ontology and the student's state and fixes it if it's wrong. For example a question move with no expected response, a help level that move doesn't allow, or positive feedback on a step that's actually false.

`validation_loop.py` runs after the LLM writes a reply. The auditor pulls the math claims out of the reply and re-checks them, and checks that the reply actually does the chosen move and doesn't give away the answer. If it fails, the issues go back to the model and it tries again, 3 attempts max. A failed reply never reaches the student. If all attempts fail it uses a fixed template for that move, and audits that too. If even that fails, or the auditor is down, the student gets a short "I can't answer safely right now" message.

## Evals

I score the problem to MathIR step against a gold set of Hungarian problems. Those are kept out of prompts and out of this repo so they stay a real test.
