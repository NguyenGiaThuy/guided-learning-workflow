using LanternKeeper;
using NUnit.Framework;

public class KeeperTests
{
    [Test]
    public void Walks()
    {
        var keeper = new Keeper();
        keeper.Walk(1f, 0f, 2f);
        Assert.AreEqual(6f, keeper.X);
    }
}
