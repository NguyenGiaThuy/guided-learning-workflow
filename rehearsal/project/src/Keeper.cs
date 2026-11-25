namespace LanternKeeper
{
    // The player's figure. Written in phase 1.
    public class Keeper
    {
        public float X, Y;
        public float Speed = 3f;

        // Owner 1.1: the speed counts per second, so a slow computer walks as far as a fast one.
        public void Walk(float directionX, float directionY, float seconds)
        {
            X += directionX * Speed * seconds;
            Y += directionY * Speed * seconds;
        }
    }
}
