using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using PrimeFlow.MailboxProbe;

public sealed class FakeCollection<T>
{
    public readonly List<T> Values;
    public FakeCollection(params T[] values) { Values = values.ToList(); }
    public int Count { get { return Values.Count; } }
    public T Item(int index) { return Values[index - 1]; }
}
public sealed class FakeCategory
{
    public string Name { get; set; }
}
public sealed class FakeItem
{
    public int Class { get; set; }
    public string Subject { get; set; }
    public string SenderName { get; set; }
    public DateTime ReceivedTime { get; set; }
    public string Categories { get; set; }
    public bool UnRead { get; set; }
    public int BodyReads;
    public string Body { get { BodyReads++; return "<script>untrusted</script> " + new String('x', 500); } }
}
public sealed class FakeItems
{
    public List<FakeItem> Values;
    public FakeItems(IEnumerable<FakeItem> values) { Values = values.ToList(); }
    public int Count { get { return Values.Count; } }
    public FakeItem Item(int index) { return Values[index - 1]; }
    public void Sort(string key, bool descending)
    {
        if (key != "[ReceivedTime]" || !descending) throw new Exception("Wrong sort");
        Values = Values.OrderByDescending(x => x.ReceivedTime).ToList();
    }
}
public sealed class FakeFolder
{
    public FakeItems Items { get; set; }
}
public sealed class FakeAccessor
{
    public object GetProperty(string property) { return new byte[] { 1, 2 }; }
    public string BinaryToString(object value) { return "owner"; }
}
public sealed class FakeOwner
{
    public string PrimarySmtpAddress { get; set; }
}
public sealed class FakeAddressEntry
{
    public FakeOwner Owner;
    public FakeOwner GetExchangeUser() { return Owner; }
}
public sealed class FakeStore
{
    public string DisplayName { get; set; }
    public int ExchangeStoreType { get; set; }
    public FakeAccessor PropertyAccessor { get { return new FakeAccessor(); } }
    public FakeCollection<FakeCategory> CategoryList = new FakeCollection<FakeCategory>(new FakeCategory { Name = "TT" }, new FakeCategory { Name = "Pagesa" });
    public bool DenyCategories;
    public FakeCollection<FakeCategory> Categories { get { if (DenyCategories) throw new Exception("Denied confidential text"); return CategoryList; } }
    public FakeFolder Folder;
    public int InboxCalls;
    public FakeFolder GetDefaultFolder(int folder)
    {
        if (folder != 6) throw new Exception("Wrong folder");
        InboxCalls++;
        return Folder;
    }
}
public sealed class FakeAccount
{
    public string SmtpAddress { get; set; }
    public int AccountType { get; set; }
    public FakeStore DeliveryStore { get; set; }
}
public sealed class FakeSession
{
    public FakeCollection<FakeAccount> Accounts { get; set; }
    public FakeCollection<FakeStore> Stores { get; set; }
    public bool Offline { get; set; }
    public int ExchangeConnectionMode { get { return Offline ? 100 : 700; } }
    public FakeAddressEntry Entry;
    public FakeAddressEntry GetAddressEntryFromID(string id) { return Entry; }
    public object GetDefaultFolder(int id) { throw new Exception("Must never read default personal inbox"); }
}

public static class ProbeTests
{
    static int passed;
    static void Assert(bool condition, string label) { if (!condition) throw new Exception(label); }
    static FakeSession Session(int messages)
    {
        var store = new FakeStore { DisplayName = "info@primexeu.com", Folder = new FakeFolder {
            Items = new FakeItems(Enumerable.Range(1, messages).Select(i => new FakeItem {
                Class = 43, Subject = "Secret subject " + i, SenderName = "Private Sender",
                ReceivedTime = new DateTime(2026, 11, 10, 10, 0, 0).AddMinutes(i),
                Categories = "TT; Pagesa", UnRead = i % 2 == 0,
            })) } };
        return new FakeSession { Accounts = new FakeCollection<FakeAccount>(new FakeAccount { SmtpAddress = " INFO@PRIMEXEU.COM ", DeliveryStore = store }), Stores = new FakeCollection<FakeStore>() };
    }
    static ProbeResult Read(FakeSession session, bool body)
    {
        var result = new ProbeResult { CheckedAt = DateTime.Now };
        try { Reader.ReadSession(session, body, result); }
        catch (Exception error) { Reader.RecordFailure(result, error); }
        return result;
    }
    static void Test(string label, Action action) { action(); passed++; Console.WriteLine("PASS " + label); }

    [STAThread]
    public static void Main(string[] args)
    {
        Test("exact mailbox, newest fifty, no body or message state writes", delegate {
            var session = Session(70);
            var items = session.Accounts.Item(1).DeliveryStore.Folder.Items;
            var originals = items.Values.ToDictionary(x => x.Subject, x => x.UnRead);
            var result = Read(session, false);
            Assert(result.Success && result.Messages.Count == 50 && result.Categories.SequenceEqual(new[] { "TT", "Pagesa" }), "read counts");
            Assert(result.Messages[0].Subject == "Secret subject 70" && result.Messages[49].Subject == "Secret subject 21", "latest fifty");
            Assert(items.Values.All(x => x.BodyReads == 0 && x.UnRead == originals[x.Subject] && x.Categories == "TT; Pagesa"), "unchanged");
        });
        Test("preview opt-in is plain text and limited to 400 characters", delegate {
            var session = Session(1);
            var result = Read(session, true);
            Assert(result.Success && result.Messages[0].Preview.Length == 401 && result.Messages[0].Preview.StartsWith("<script>"), "plain text truncation");
        });
        Test("a display name alone never selects another mailbox", delegate {
            var session = Session(2);
            var store = session.Accounts.Item(1).DeliveryStore;
            session.Accounts.Item(1).SmtpAddress = "manager@example.com";
            session.Stores = new FakeCollection<FakeStore>(store);
            session.Entry = new FakeAddressEntry { Owner = new FakeOwner { PrimarySmtpAddress = "manager@example.com" } };
            var result = Read(session, false);
            Assert(!result.Success && result.Messages.Count == 0 && store.InboxCalls == 0, "no personal mailbox fallback");
        });
        Test("additional mailbox requires exact Exchange owner address", delegate {
            var session = Session(1);
            var store = session.Accounts.Item(1).DeliveryStore;
            session.Accounts = new FakeCollection<FakeAccount>(); session.Stores = new FakeCollection<FakeStore>(store);
            session.Entry = new FakeAddressEntry { Owner = new FakeOwner { PrimarySmtpAddress = Reader.Target } };
            var result = Read(session, false);
            Assert(result.Success && result.IdentityMethod == "exact_exchange_owner_smtp", "owner identity");
        });
        Test("duplicate mailbox matches stop without reading", delegate {
            var session = Session(1); var account = session.Accounts.Item(1);
            session.Accounts = new FakeCollection<FakeAccount>(account, account);
            var result = Read(session, false);
            Assert(!result.Success && account.DeliveryStore.InboxCalls == 0, "ambiguity");
        });
        Test("non-Exchange store is rejected", delegate {
            var session = Session(1); session.Accounts.Item(1).DeliveryStore.ExchangeStoreType = 3;
            Assert(!Read(session, false).Success && session.Accounts.Item(1).DeliveryStore.InboxCalls == 0, "PST rejected");
        });
        Test("category denial cannot claim overall success or expose raw error", delegate {
            var session = Session(1); session.Accounts.Item(1).DeliveryStore.DenyCategories = true;
            var result = Read(session, false);
            Assert(!result.Success && !result.CategoriesRead && !result.InboxRead && !result.Failure.Contains("confidential"), "failure safety");
        });
        Test("empty Inbox and categories are valid empty reads", delegate {
            var session = Session(0); session.Accounts.Item(1).DeliveryStore.CategoryList = new FakeCollection<FakeCategory>();
            var result = Read(session, false);
            Assert(result.Success && result.Messages.Count == 0 && result.Categories.Count == 0, "empty results");
        });
        Test("offline success stays explicitly a local cached result", delegate {
            var session = Session(1); session.Offline = true;
            var result = Read(session, false);
            Assert(result.Success && result.Offline && result.ConnectionMode.Contains("cached") && result.Diagnostic().Contains("Graph: NOT_TESTED"), "offline distinction");
        });
        Test("non-email items do not consume fifty-message limit", delegate {
            var session = Session(62); var items = session.Accounts.Item(1).DeliveryStore.Folder.Items;
            items.Values[61].Class = 53;
            var result = Read(session, false);
            Assert(result.Success && result.Messages.Count == 50 && result.Messages[0].Subject == "Secret subject 61", "mail only");
        });
        Test("clipboard diagnostics exclude all email contents and category names", delegate {
            var result = Read(Session(2), true);
            string text = result.Diagnostic();
            Assert(!text.Contains("Secret subject") && !text.Contains("Private Sender") && !text.Contains("Pagesa") && !text.Contains("<script>"), "content-free diagnostic");
            Assert(text.Contains("Mailbox type: NOT_DETERMINED") && text.Contains("PrimeFlow upload: NONE"), "truthful claims");
        });
        if (args.Length == 1)
        {
            // Render the program's own controls with synthetic data. No Outlook or external UI.
            using (var form = new ProbeForm())
            {
                form.ShowResult(Read(Session(2), false));
                CreateHandles(form);
                form.PerformLayout();
                foreach (System.Windows.Forms.Control control in form.Controls) control.PerformLayout();
                using (var bitmap = new Bitmap(form.Width, form.Height))
                {
                    form.DrawToBitmap(bitmap, new Rectangle(0, 0, bitmap.Width, bitmap.Height));
                    bitmap.Save(args[0]);
                }
            }
        }
        Console.WriteLine(passed + " tests passed. No real Outlook session accessed.");
    }

    static void CreateHandles(System.Windows.Forms.Control control)
    {
        IntPtr handle = control.Handle;
        foreach (System.Windows.Forms.Control child in control.Controls) CreateHandles(child);
        control.PerformLayout();
    }
}
