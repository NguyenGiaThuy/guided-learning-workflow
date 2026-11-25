import os
import tempfile
import time
import unittest
from pathlib import Path

from helpers import make_project
from gl import project, scan


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, data):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return p

    def test_todos_in_order(self):
        p = self.write("a.cs", "// TODO(owner 1.2) b\n// TODO(owner 1.1) a\n// TODO(owner 2.1)\n")
        self.assertEqual(scan.todos(p), ["1.2", "1.1", "2.1"])

    def test_todo_in_any_comment_style(self):
        p = self.write("a.txt", "// TODO(owner 1.1)\n# TODO(owner 1.2)\n-- TODO(owner 1.3)\n")
        self.assertEqual(scan.todos(p), ["1.1", "1.2", "1.3"])

    def test_duplicates_once_missing_file_bom_crlf_bad_bytes(self):
        self.assertEqual(scan.todos(self.root / "none.cs"), [])
        p = self.write("a.cs", b"\xef\xbb\xbf// TODO(owner 1.1)\r\n// TODO(owner 1.1)\r\n\xff\xfe TODO(owner 3.4)")
        self.assertEqual(scan.todos(p), ["1.1", "3.4"])

    def test_removed_finds_only_lost_ones(self):
        before = "TODO(owner 1.1) TODO(owner 1.2) TODO(owner 1.3)"
        after = "TODO(owner 1.2)"
        self.assertEqual(scan.removed(before, after), ["1.1", "1.3"])
        self.assertEqual(scan.removed(after, before), [])

    def test_last_code_change_and_owner_marks(self):
        root = make_project(self.tmp.name + "/p")
        proj = project.find(root)
        self.assertEqual(scan.last_code_change(proj), 0.0)
        a = self.write("p/src/b/B.cs", 'x\n[Explicit("Owner")]\n')
        b = self.write("p/src/A.cs", '[Explicit("Owner")] [Explicit("Owner")]\n')
        self.write("p/src/readme.md", '[Explicit("Owner")]\n')
        os.utime(a, (1000, 1000))
        os.utime(b, (2000, 2000))
        self.assertEqual(scan.last_code_change(proj), 2000)
        self.assertEqual(scan.owner_marks(proj, ["Explicit.Owner"]), ["src/A.cs:1", "src/b/B.cs:2"])
        self.assertEqual(scan.owner_marks(proj, ["Explicit.Own", "Owner.Other"]), [])
        self.assertEqual(scan.owner_marks(proj, []), [])

    def declares(self, line, test="GameTests.Move"):
        return scan.declares("class GameTests {\n%s\n}\n" % line, test)

    def test_declarations(self):
        for line in ("public void Move() {}", "    void Move () {", "[Test] public async Task Move()",
                     "async Task<int> Move()", "[UnityTest] public IEnumerator<int> Move()", "IEnumerator Move() {",
                     "Dictionary<string, List<int>> Move()", "int[] Move()", "int[][] Move()", "void Move<T>(T x)",
                     "public static void Move<TKey, TValue> (TKey k)", "def Move(self):", "async def Move(self):",
                     "fn Move() {", "func Move():", "function Move() {", "fun Move() {", "\tvoid\tMove(int speed)",
                     "class GameTests { void Other() {} void Move() {} }", "g.Move(); void Move() {}",
                     "[Category(\"http://x\")] public void Move()"):
            self.assertTrue(self.declares(line), line)
        self.assertTrue(scan.declares("def test_move(self):\n", "test_move"))   # a name without a class

    def test_calls_and_comments_are_no_declarations(self):
        for line in ("g.Move();", "Move();", "    Move();", "return Move();", "return new Move();", "await Move();",
                     "yield return Move();", "else Move();", "throw Move();", "var x = Move();", "x = y + Move()",
                     "if (Move()) {}", "if (x && Move()) {}", "foreach (var a in Move()) {}", "a is Move(1)",
                     "x not in Move()", "not Move()", "a and Move()", "b or Move()", "case Move():", "assert Move()",
                     "new Move();", "() => Move();", "if (a > Move()) {}", "p-> Move();", "run(a, Move);",
                     "if Move():", "elif Move():", "while Move():", "do Move();", "raise Move()", "with Move() as m:",
                     "void Moves() {}", "void ReMove() {}", "void move() {}", "void Move;", "int Move = 3;",
                     "// void Move() {}", "   // the old void Move()", "# def Move(self):", "-- void Move()",
                     " * void Move()", "/* void Move() */"):
            self.assertFalse(self.declares(line), line)

    def test_a_custom_name_is_declared_by_its_literal(self):
        for line in ('[TestCase(1, TestName="MoveOne")]', "[TestCase(1, TestName = 'MoveOne')]",
                     'yield return new TestCaseData(1).SetName("MoveOne");', 'x.SetName(@"MoveOne")'):
            self.assertTrue(self.declares(line, "Game.GameTests.MoveOne"), line)
        self.assertTrue(self.declares('[TestCase(1, TestName="Move one")]', "Game.GameTests.Move one"))
        for line in ('[TestCase(1, TestName="MoveOneMore")]', '[TestCase(1, TestName="A MoveOne")]', 'x = MoveOne;',
                     '// [TestCase(1, TestName="MoveOne")]', "x = \"MoveOne';"):
            self.assertFalse(self.declares(line, "Game.GameTests.MoveOne"), line)
        self.assertFalse(scan.declares('class Other { [TestCase(1, TestName="MoveOne")] }', "GameTests.MoveOne"))

    def test_a_macro_declares_a_test(self):
        for line in ("TEST(GameTests, Move) {", "TEST_F(GameTests,Move)", "  TEST_F ( GameTests , Move ) {"):
            self.assertTrue(self.declares(line), line)
        for line in ("TEST(GameTests, Moves) {", "TEST(Other, Move)", "// TEST(GameTests, Move)", "RUN(GameTests, Move)",
                     "MYTEST(GameTests, Move)"):
            self.assertFalse(self.declares(line), line)

    def test_generic_arguments_do_not_count(self):
        for name, parts in (("Game.A.Move<Int32>(1)", ("A", "Move")), ("Game.A.Move<System.Int32>", ("A", "Move")),
                            ("A.Move<Dictionary<System.Int32,List<X>>>(1)", ("A", "Move")),
                            ("Game.A<System.Int32>.Move", ("A", "Move")), ("A.Move(\"a<b>.c\")", ("A", "Move")),
                            ("A.a<b", ("A", "a<b")), ("A.a < b > c", ("A", "a < b > c")), ("Move", ("Move",))):
            self.assertEqual(scan.class_and_method(name), parts, name)
        self.assertTrue(self.declares("void Move<T>(T x) {}", "GameTests.Move<Int32>(1)"))

    def test_a_fixture_with_arguments_is_declared(self):
        code = "namespace Ns {\n[TestFixture(1)]\nclass Fixture {\n  public Fixture(int n) {}\n  void Method() {}\n}\n}"
        self.assertTrue(scan.has_test(code, "Ns.Fixture(1).Method"))   # as it was
        self.assertTrue(scan.declares(code, "Ns.Fixture(1).Method"))
        self.assertTrue(scan.declares(code.replace("Fixture {", "Fixture<T> {"), "Ns.Fixture<Int32>(1).Method"))

    def test_long_lines_and_many_tests_are_quick(self):
        start = time.monotonic()
        for line in ("a" * 32000, "Move" * 8000, "Move<" * 6400, "<a> " * 8000, "a " * 16000, " " * 32000 + "Move",
                     "TEST" * 8000, "TEST( " * 5300, "Move " * 6400, "\"Move, " * 5000, "Move" + " " * 32000):
            self.assertFalse(self.declares(line + " GameTests Move", "GameTests.Move"), line[:20])
        self.assertTrue(self.declares("a" * 32000 + " void Move()", "GameTests.Move"))
        names = ["test%d" % i for i in range(1000)]
        code = "class A {\n%s\n}\n" % "\n".join("  void %s() {}\n  // a\n  b();" % n for n in names)
        root = make_project(self.tmp.name + "/q", files={"src/A.cs": code})
        self.assertEqual(len(scan.declared_tests(project.find(root), ["A." + n for n in names])), 1000)
        self.assertLess(time.monotonic() - start, 5)

    def test_a_declaration_needs_the_class_in_the_same_file(self):
        self.assertFalse(scan.declares("class GameTests2 { void Move() {} }", "GameTests.Move"))
        self.assertTrue(scan.declares("class GameTests { void Move() {} }", "Lantern.GameTests.Move(1, 2)"))
        root = make_project(self.tmp.name + "/p", files={"src/A.cs": "class A { void x() { b.y(); } }",
                                                         "src/B.cs": "class B { int y() { return x(); } }"})
        self.assertEqual(scan.declared_tests(project.find(root), ["A.x", "A.y", "B.x", "B.y"]), ["A.x", "B.y"])
        self.assertEqual(scan.declared_tests(project.find(root), []), [])


if __name__ == "__main__":
    unittest.main()
