using LanternKeeper;
using NUnit.Framework;

public class LanternTests
{
    [Test]
    [Explicit("Owner")]
    public void Burns()
    {
        var lantern = new Lantern { Oil = 3f };
        lantern.Burn(2f);
        Assert.AreEqual(1f, lantern.Oil);
        lantern.Burn(2f);
        Assert.AreEqual(0f, lantern.Oil);
    }

    [Test]
    [Explicit("Owner")]
    public void Shines()
    {
        var lantern = new Lantern();
        Assert.AreEqual(1f, lantern.LightAt(0f));
        Assert.AreEqual(0f, lantern.LightAt(lantern.Radius));
        lantern.Oil = 0f;
        Assert.AreEqual(0f, lantern.LightAt(0f));
    }
}
