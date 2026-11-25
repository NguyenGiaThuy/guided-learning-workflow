using System;
using System.Collections.Generic;

namespace LanternKeeper
{
    // An enemy that flies to the light.
    public class Moth
    {
        public float X, Y;
        public float Speed = 2f;
        public float SightRange = 6f;
        public float Energy = 10f;
        public float FullEnergy = 10f;

        // Owner 1.1: the nearest lantern in range, or null.
        public Lantern FindTarget(IEnumerable<Lantern> lanterns)
        {
            Lantern best = null;
            float bestDistance = SightRange;
            foreach (Lantern lantern in lanterns)
            {
                float distance = DistanceTo(lantern);
                if (distance <= bestDistance)
                {
                    best = lantern;
                    bestDistance = distance;
                }
            }
            return best;
        }

        // Owner 1.2: one step towards the target, never past it.
        public void Chase(Lantern target, float seconds)
        {
            float distance = DistanceTo(target);
            if (distance == 0f) return;
            float step = Math.Min(Speed * seconds, distance);
            X += (target.X - X) / distance * step;
            Y += (target.Y - Y) / distance * step;
            Energy -= step;
        }

        public bool NeedsRest()
        {
            // TODO(owner 1.3) A moth without energy rests until half of its energy is back.
            //   if the energy is used up: it rests
            //   if it rests already: it goes on until it has half of FullEnergy
            // Hint: one field must remember whether it is resting. Two limits instead of one
            // keep it from switching back and forth in every frame.
            return false;
        }

        private float DistanceTo(Lantern lantern)
        {
            float dx = lantern.X - X, dy = lantern.Y - Y;
            return (float)Math.Sqrt(dx * dx + dy * dy);
        }
    }
}
