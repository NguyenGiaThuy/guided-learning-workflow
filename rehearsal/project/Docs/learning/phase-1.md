# Phase 1

## Notes for later

- The keeper walks with the arrow keys. The camera does not follow yet.

## Answers

### q1
The update runs once per frame, and I multiply by the time that has passed.
After a hint: the speed is per second, so the number of frames does not matter.

## Concept summary

### Game loop
Idea: read the input, change the world, draw it, again and again (usual name: game loop with delta time). Here `Keeper.Walk` gets the seconds since the last frame. It resembles a request loop that also runs when nobody sends a request. Alternative not chosen: a fixed time step. What went wrong: at first the keeper was twice as fast on a fast screen.

## Lessons

- Multiply by the time of the frame.
- Small steps are easier to test than a whole walk.
- Do differently: write the numbers down before tuning.

## Process

Surprised me: how much of the feeling comes from one number
Differently: write the numbers down before tuning

## Scorecard

Build: 1/1 owner scripts pass their tests. Highest help level: Owner 1 Keeper 2.
Predict: 1/1 tweaks had the right predicted direction.
Balance: 1/1 targets met.
Explain: Game loop: with help.
Process: Surprised me: how much of the feeling comes from one number | Differently: write the numbers down before tuning
