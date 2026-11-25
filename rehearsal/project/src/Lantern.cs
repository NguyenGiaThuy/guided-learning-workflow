namespace LanternKeeper
{
    // The light the keeper carries. It burns oil and draws moths.
    public class Lantern
    {
        public float X, Y;
        public float Oil = 100f;
        public float Radius = 5f;
        public float OilPerSecond = 1f;

        public void Burn(float seconds)
        {
            // TODO(owner 2.1) The lantern uses oil over time, and never has less than none.
            //   oil = oil - use per second * time of this step
            // Hint: the same idea as the speed of the keeper in phase 1.
        }

        public float LightAt(float distance)
        {
            // TODO(owner 2.2) Full light (1) at the lantern, none (0) at the radius and beyond.
            //   without oil there is no light at all
            // Hint: engines call this falloff. A straight line is enough here.
            return 0f;
        }
    }
}
