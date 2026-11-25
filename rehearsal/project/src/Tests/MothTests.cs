using LanternKeeper;
using NUnit.Framework;

public class MothTests
{
    [Test]
    public void Turns()
    {
        var near = new Lantern { X = 2f };
        var far = new Lantern { X = 5f };
        Assert.AreSame(near, new Moth().FindTarget(new[] { far, near }));
    }

    [Test]
    public void Chases()
    {
        var moth = new Moth();
        moth.Chase(new Lantern { X = 1f }, 10f);
        Assert.AreEqual(1f, moth.X);
    }

    [Test]
    [Explicit("Owner")]
    public void Rests()
    {
        var moth = new Moth { Energy = 0f };
        Assert.IsTrue(moth.NeedsRest());
        moth.Energy = 4f;
        Assert.IsTrue(moth.NeedsRest());
        moth.Energy = 5f;
        Assert.IsFalse(moth.NeedsRest());
    }
}
