# StudAI code sample: the tutor turn is checked, not trusted

StudAI is a Hungarian AI math tutor I am building. This folder holds two small modules from the backend. The full repo is private.

## The idea

The LLM is not the math authority. It writes the words a student sees, and that is all. The math and the teaching decisions come from a deterministic system around it.

A tutor turn works like this:

1. The student's problem is compiled into MathIR, a typed representation of entities, statements and goals.
2. A deterministic verifier and solver work out what is true and what the student's step means.
3. The system keeps explicit student state (help level, errors, misconceptions) and picks a teaching move from a fixed action ontology, such as ASK_NEXT_STEP or ASK_JUSTIFICATION.
4. `action_validator.py` checks that chosen action against the ontology and the current state, and repairs it if it is invalid (for example a question move with no response demand, or a help level that is not allowed).
5. Only then does the LLM write the reply.
6. `validation_loop.py` runs generate, then audit, then repair. The auditor pulls math claims out of the reply and re-checks them with the verifier, and checks that the reply really performs the chosen move and does not leak the answer. A failed reply is never shown to the student. After a few failed attempts the system falls back to a deterministic template, which is audited again.

## Evaluation

Problem-to-MathIR fidelity is scored against a held-out gold set of Hungarian problems. The gold items are kept out of prompts and training data so the scores stay honest. That is why they are not in this sample.

## Files

- `validation_loop.py`: the generate, audit, repair loop with a safe fallback.
- `action_validator.py`: deterministic validation and repair of the chosen teaching move.
